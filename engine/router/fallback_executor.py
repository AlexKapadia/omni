"""The fallback executor: kill-switch gate, chain walk, retry-once, ledger.

Purpose: the ONE code path every external model call goes through. For a
task it (1) checks the global kill switch, (2) resolves the routing-table
chain for the current keyed world, (3) walks primary -> fallbacks with
retry-once semantics per the error taxonomy, (4) logs EVERY attempt to the
append-only router ledger, and (5) degrades gracefully with a typed
``RouterUnavailableError`` when the whole chain fails.
Pipeline position: the router's public entry point — M2+ pipelines call
:meth:`ProviderRouter.route`; provider clients sit below; the ledger
repository records to SQLite.

Security invariants:
- KILL SWITCH FIRST (fail closed): checked before task resolution, so no
  task type — known or unknown — can reach a provider while it is engaged.
- Deny by default: unknown task types refuse (``UnknownTaskTypeError``).
- Retry policy: auth errors NEVER retry (a bad key cannot get better);
  ratelimit/timeout/server retry ONCE on the same provider, then cascade.
- Ledger failures propagate: an unlogged external call must not succeed
  silently (every-call-logged invariant).
"""

import asyncio
import time
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime

from engine.router.completion_contract import (
    ChatMessage,
    CompletionRequest,
    Provider,
    ProviderCompletion,
    ProviderCompletionClient,
    RoutedCompletion,
    ToolSpec,
)
from engine.router.model_pricing import estimate_cost_usd
from engine.router.router_errors import (
    KillSwitchEngagedError,
    ProviderCallError,
    ProviderErrorClass,
    ProviderFailure,
    RouterUnavailableError,
)
from engine.router.router_ledger_repository import RouterLedgerEntry
from engine.router.routing_table import ProviderModelSlot, resolve_route
from engine.security.kill_switch import kill_switch_engaged

# Brief pause before the single ratelimit retry — long enough for burst
# quotas to breathe, short enough not to blow live latency budgets twice.
RATELIMIT_RETRY_DELAY_SECONDS = 0.5

# Types for the injectable seams (tested without real time or SQLite).
LedgerRecorder = Callable[[RouterLedgerEntry], Awaitable[None]]
SleepFunction = Callable[[float], Awaitable[None]]
Clock = Callable[[], float]


def _utc_now_iso() -> str:
    """ISO-8601 UTC timestamp — the schema's pinned time format."""
    return datetime.now(tz=UTC).isoformat()


@dataclass(frozen=True)
class _ProviderAttemptOutcome:
    """What one provider (including its single retry) produced."""

    completion: ProviderCompletion | None
    latency_ms: int
    calls_made: int
    error: ProviderCallError | None


class ProviderRouter:
    """Routes completion work across providers with typed degradation.

    ``clients`` holds ONLY keyed providers (built by the registry), so the
    keyed world used for route resolution is exactly the callable world.
    """

    def __init__(
        self,
        clients: Mapping[Provider, ProviderCompletionClient],
        record_ledger_entry: LedgerRecorder,
        *,
        sleep: SleepFunction = asyncio.sleep,
        clock: Clock = time.perf_counter,
    ) -> None:
        self._clients = dict(clients)
        self._record_ledger_entry = record_ledger_entry
        self._sleep = sleep
        self._clock = clock

    async def route(
        self,
        task_type: str,
        system_frame: str,
        messages: tuple[ChatMessage, ...],
        *,
        tools: tuple[ToolSpec, ...] = (),
        json_schema: dict[str, object] | None = None,
        max_tokens: int = 4096,
    ) -> RoutedCompletion:
        """Execute ``task_type`` through its provider chain.

        Raises (all typed, all plain-voice): ``KillSwitchEngagedError``,
        ``UnknownTaskTypeError``, ``MisconfiguredRouteError``,
        ``RouterUnavailableError``.
        """
        # SECURITY GATE — kill switch BEFORE anything else (fail closed):
        # even an unknown task type must not observe a working router.
        if kill_switch_engaged():
            raise KillSwitchEngagedError
        keyed = frozenset(provider.value for provider in self._clients)
        resolved = resolve_route(task_type, keyed)  # deny-by-default inside
        failures: list[ProviderFailure] = []
        total_calls = 0
        for slot in resolved.attempts:
            request = CompletionRequest(
                task_type=resolved.task_type,
                model=slot.model,
                system_frame=system_frame,
                messages=messages,
                # Latency budget from the table, enforced per attempt.
                timeout_seconds=resolved.latency_budget_p95_ms / 1000.0,
                tools=tools,
                json_schema=json_schema,
                max_tokens=max_tokens,
            )
            outcome = await self._attempt_provider(slot, request)
            total_calls += outcome.calls_made
            if outcome.completion is not None:
                return RoutedCompletion(
                    completion=outcome.completion,
                    provider=slot.provider,
                    model=slot.model,
                    latency_ms=outcome.latency_ms,
                    attempts=total_calls,
                )
            if outcome.error is not None:
                failures.append(
                    ProviderFailure(
                        provider=slot.provider.value,
                        model=slot.model,
                        error_class=outcome.error.error_class,
                        message=outcome.error.message,
                    )
                )
            # cascade to the next slot in the chain
        # Whole chain exhausted: degrade gracefully with the full story.
        raise RouterUnavailableError(task_type, tuple(failures))

    async def _attempt_provider(
        self, slot: ProviderModelSlot, request: CompletionRequest
    ) -> _ProviderAttemptOutcome:
        """Try one provider with retry-once semantics; log every attempt.

        Retry policy (taxonomy-driven): auth breaks out immediately;
        ratelimit sleeps briefly then retries once; timeout/server retry
        once immediately. Every call — success or failure — gets its own
        ledger row.
        """
        client = self._clients[slot.provider]
        last_error: ProviderCallError | None = None
        calls_made = 0
        for retry_index in (0, 1):
            calls_made += 1
            started = self._clock()
            try:
                completion = await client.complete(request)
            except ProviderCallError as error:
                latency_ms = self._elapsed_ms(started)
                await self._log_attempt(request, slot, latency_ms, error=error)
                last_error = error
                if not error.retryable:
                    break  # auth: retrying a bad key burns budget for nothing
                if retry_index == 0 and error.error_class is ProviderErrorClass.RATELIMIT:
                    await self._sleep(RATELIMIT_RETRY_DELAY_SECONDS)
                continue  # timeout/server retry immediately, once
            latency_ms = self._elapsed_ms(started)
            await self._log_attempt(request, slot, latency_ms, completion=completion)
            return _ProviderAttemptOutcome(
                completion=completion,
                latency_ms=latency_ms,
                calls_made=calls_made,
                error=None,
            )
        return _ProviderAttemptOutcome(
            completion=None, latency_ms=0, calls_made=calls_made, error=last_error
        )

    def _elapsed_ms(self, started: float) -> int:
        return round((self._clock() - started) * 1000)

    async def _log_attempt(
        self,
        request: CompletionRequest,
        slot: ProviderModelSlot,
        latency_ms: int,
        *,
        completion: ProviderCompletion | None = None,
        error: ProviderCallError | None = None,
    ) -> None:
        """Append one ledger row (exact tokens/cost on success, zeros on
        failure). Ledger errors propagate — no unlogged external calls."""
        prompt_tokens = completion.prompt_tokens if completion is not None else 0
        completion_tokens = completion.completion_tokens if completion is not None else 0
        entry = RouterLedgerEntry(
            ts=_utc_now_iso(),
            task_type=request.task_type.value,
            provider=slot.provider.value,
            model=slot.model,
            latency_ms=latency_ms,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            # Exact Decimal cost — zero tokens costs exactly Decimal(0).
            est_cost_usd=estimate_cost_usd(slot.model, prompt_tokens, completion_tokens),
            outcome="ok" if completion is not None else "error",
            error_class=None if error is None else error.error_class.value,
        )
        await self._record_ledger_entry(entry)
