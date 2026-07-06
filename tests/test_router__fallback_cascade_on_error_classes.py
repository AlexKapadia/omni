"""Fallback-executor cascade tests: retry-once semantics per error class.

Mocks at the client boundary (no network, no SDKs): scripted fake clients
raise taxonomy errors on demand and record every call. Pins the policy —
auth NEVER retries (immediate cascade), ratelimit/timeout/server retry
exactly ONCE then cascade, every call lands a ledger row, and a fully
failed chain degrades into a typed RouterUnavailableError that names every
provider and why.
"""

from decimal import Decimal

import pytest

from engine.router.completion_contract import (
    ChatMessage,
    CompletionRequest,
    Provider,
    ProviderCompletion,
    ProviderCompletionClient,
)
from engine.router.fallback_executor import (
    RATELIMIT_RETRY_DELAY_SECONDS,
    ProviderRouter,
)
from engine.router.router_errors import (
    ProviderCallError,
    ProviderErrorClass,
    RouterUnavailableError,
)
from engine.router.router_ledger_repository import RouterLedgerEntry
from engine.router.routing_table import GEMINI_FLASH_MODEL, GROQ_FAST_MODEL

MESSAGES = (ChatMessage(role="user", content="transcript excerpt (data)"),)


def _ok(provider: Provider, model: str) -> ProviderCompletion:
    return ProviderCompletion(
        text="fine",
        provider=provider,
        model=model,
        prompt_tokens=100,
        completion_tokens=50,
    )


def _err(provider: Provider, model: str, error_class: ProviderErrorClass) -> ProviderCallError:
    return ProviderCallError(
        provider=provider.value,
        model=model,
        error_class=error_class,
        message=f"synthetic {error_class} failure",
    )


class ScriptedClient(ProviderCompletionClient):
    """Returns/raises the scripted outcomes in order; records every call."""

    def __init__(
        self, provider: Provider, script: list[ProviderCompletion | ProviderCallError]
    ) -> None:
        self.provider = provider
        self._script = list(script)
        self.calls: list[CompletionRequest] = []

    async def complete(self, request: CompletionRequest) -> ProviderCompletion:
        self.calls.append(request)
        if not self._script:
            raise AssertionError(f"{self.provider} called more times than scripted")
        outcome = self._script.pop(0)
        if isinstance(outcome, ProviderCallError):
            raise outcome
        return outcome


class RecordingLedger:
    """Collects ledger rows; the append-only SQLite path is tested separately."""

    def __init__(self) -> None:
        self.entries: list[RouterLedgerEntry] = []

    async def record(self, entry: RouterLedgerEntry) -> None:
        self.entries.append(entry)


class RecordingSleep:
    """Captures retry backoff delays without actually sleeping."""

    def __init__(self) -> None:
        self.delays: list[float] = []

    async def __call__(self, seconds: float) -> None:
        self.delays.append(seconds)


def _router(
    clients: dict[Provider, ProviderCompletionClient],
) -> tuple[ProviderRouter, RecordingLedger, RecordingSleep]:
    ledger = RecordingLedger()
    sleep = RecordingSleep()
    router = ProviderRouter(clients, ledger.record, sleep=sleep)
    return router, ledger, sleep


# live_extraction pair-world chain: groq/llama -> gemini/flash. All cascade
# tests ride this chain so expectations are boundary-exact.


async def test_primary_success_never_touches_the_fallback() -> None:
    groq = ScriptedClient(Provider.GROQ, [_ok(Provider.GROQ, GROQ_FAST_MODEL)])
    gemini = ScriptedClient(Provider.GEMINI, [])
    router, ledger, sleep = _router({Provider.GROQ: groq, Provider.GEMINI: gemini})
    result = await router.route("live_extraction", "frame", MESSAGES)
    assert result.provider is Provider.GROQ
    assert result.attempts == 1
    assert len(groq.calls) == 1
    assert gemini.calls == []  # fallback untouched
    assert sleep.delays == []
    assert [e.outcome for e in ledger.entries] == ["ok"]


@pytest.mark.parametrize(
    "error_class", [ProviderErrorClass.TIMEOUT, ProviderErrorClass.SERVER]
)
async def test_timeout_and_server_retry_once_then_succeed_without_backoff(
    error_class: ProviderErrorClass,
) -> None:
    groq = ScriptedClient(
        Provider.GROQ,
        [_err(Provider.GROQ, GROQ_FAST_MODEL, error_class), _ok(Provider.GROQ, GROQ_FAST_MODEL)],
    )
    gemini = ScriptedClient(Provider.GEMINI, [])
    router, ledger, sleep = _router({Provider.GROQ: groq, Provider.GEMINI: gemini})
    result = await router.route("live_extraction", "frame", MESSAGES)
    assert result.provider is Provider.GROQ
    assert result.attempts == 2  # exactly one retry, same provider
    assert len(groq.calls) == 2
    assert gemini.calls == []
    assert sleep.delays == []  # no backoff for timeout/server
    assert [e.outcome for e in ledger.entries] == ["error", "ok"]
    assert ledger.entries[0].error_class == error_class.value


async def test_ratelimit_retries_once_with_the_documented_backoff() -> None:
    groq = ScriptedClient(
        Provider.GROQ,
        [
            _err(Provider.GROQ, GROQ_FAST_MODEL, ProviderErrorClass.RATELIMIT),
            _ok(Provider.GROQ, GROQ_FAST_MODEL),
        ],
    )
    gemini = ScriptedClient(Provider.GEMINI, [])
    router, _, sleep = _router({Provider.GROQ: groq, Provider.GEMINI: gemini})
    result = await router.route("live_extraction", "frame", MESSAGES)
    assert result.provider is Provider.GROQ
    assert len(groq.calls) == 2
    assert sleep.delays == [RATELIMIT_RETRY_DELAY_SECONDS]  # exactly one backoff


async def test_two_retryable_failures_cascade_to_the_fallback() -> None:
    groq = ScriptedClient(
        Provider.GROQ,
        [
            _err(Provider.GROQ, GROQ_FAST_MODEL, ProviderErrorClass.SERVER),
            _err(Provider.GROQ, GROQ_FAST_MODEL, ProviderErrorClass.SERVER),
        ],
    )
    gemini = ScriptedClient(Provider.GEMINI, [_ok(Provider.GEMINI, GEMINI_FLASH_MODEL)])
    router, ledger, _ = _router({Provider.GROQ: groq, Provider.GEMINI: gemini})
    result = await router.route("live_extraction", "frame", MESSAGES)
    assert result.provider is Provider.GEMINI
    assert result.model == GEMINI_FLASH_MODEL
    assert len(groq.calls) == 2  # boundary-exact: one retry, not two
    assert len(gemini.calls) == 1
    assert result.attempts == 3
    assert [e.outcome for e in ledger.entries] == ["error", "error", "ok"]


async def test_auth_error_does_not_retry_and_cascades_immediately() -> None:
    """A bad key cannot get better: exactly ONE call to the failing
    provider, no backoff sleep, straight to the fallback."""
    groq = ScriptedClient(
        Provider.GROQ, [_err(Provider.GROQ, GROQ_FAST_MODEL, ProviderErrorClass.AUTH)]
    )
    gemini = ScriptedClient(Provider.GEMINI, [_ok(Provider.GEMINI, GEMINI_FLASH_MODEL)])
    router, ledger, sleep = _router({Provider.GROQ: groq, Provider.GEMINI: gemini})
    result = await router.route("live_extraction", "frame", MESSAGES)
    assert result.provider is Provider.GEMINI
    assert len(groq.calls) == 1  # NO retry on auth — the whole point
    assert sleep.delays == []
    assert result.attempts == 2
    assert ledger.entries[0].error_class == "auth"


async def test_all_providers_failing_degrades_into_router_unavailable() -> None:
    groq = ScriptedClient(
        Provider.GROQ,
        [
            _err(Provider.GROQ, GROQ_FAST_MODEL, ProviderErrorClass.TIMEOUT),
            _err(Provider.GROQ, GROQ_FAST_MODEL, ProviderErrorClass.TIMEOUT),
        ],
    )
    gemini = ScriptedClient(
        Provider.GEMINI,
        [_err(Provider.GEMINI, GEMINI_FLASH_MODEL, ProviderErrorClass.AUTH)],
    )
    router, ledger, _ = _router({Provider.GROQ: groq, Provider.GEMINI: gemini})
    with pytest.raises(RouterUnavailableError) as excinfo:
        await router.route("live_extraction", "frame", MESSAGES)
    failures = excinfo.value.failures
    # The typed failure list carries WHICH providers failed and WHY.
    assert [(f.provider, f.error_class) for f in failures] == [
        ("groq", ProviderErrorClass.TIMEOUT),
        ("gemini", ProviderErrorClass.AUTH),
    ]
    # Plain-voice message: names the task and both providers, no stack noise.
    message = str(excinfo.value)
    assert "live_extraction" in message
    assert "groq" in message and "gemini" in message
    # Ledger saw every attempt: groq x2 (retry), gemini x1 (auth, no retry).
    assert [(e.provider, e.outcome) for e in ledger.entries] == [
        ("groq", "error"),
        ("groq", "error"),
        ("gemini", "error"),
    ]


async def test_every_ledger_row_is_exact_failed_rows_cost_zero() -> None:
    groq = ScriptedClient(
        Provider.GROQ,
        [
            _err(Provider.GROQ, GROQ_FAST_MODEL, ProviderErrorClass.SERVER),
            _ok(Provider.GROQ, GROQ_FAST_MODEL),
        ],
    )
    gemini = ScriptedClient(Provider.GEMINI, [])
    router, ledger, _ = _router({Provider.GROQ: groq, Provider.GEMINI: gemini})
    await router.route("live_extraction", "frame", MESSAGES)
    error_row, ok_row = ledger.entries
    assert error_row.prompt_tokens == 0 and error_row.completion_tokens == 0
    assert error_row.est_cost_usd == Decimal(0)
    # Success row: provider-reported tokens (100/50) at llama-3.3 list price,
    # exact to the unit: 100*0.59/1M + 50*0.79/1M = 0.0000985 USD.
    assert ok_row.prompt_tokens == 100 and ok_row.completion_tokens == 50
    assert ok_row.est_cost_usd == Decimal("0.0000985")
    assert ok_row.task_type == "live_extraction"
    assert ok_row.model == GROQ_FAST_MODEL


async def test_request_carries_the_tables_latency_budget_as_timeout() -> None:
    """Clients must receive the routing table's budget as their timeout —
    live_extraction: 1200 ms -> 1.2 s, boundary-exact."""
    groq = ScriptedClient(Provider.GROQ, [_ok(Provider.GROQ, GROQ_FAST_MODEL)])
    gemini = ScriptedClient(Provider.GEMINI, [])
    router, _, _ = _router({Provider.GROQ: groq, Provider.GEMINI: gemini})
    await router.route("live_extraction", "frame", MESSAGES)
    assert groq.calls[0].timeout_seconds == 1.2
    assert groq.calls[0].system_frame == "frame"
    assert groq.calls[0].messages == MESSAGES


async def test_unkeyed_anthropic_world_never_constructs_an_anthropic_call() -> None:
    """agentic_tools in the pair world must run entirely on Gemini —
    no client lookup for a provider that has no key/client."""
    gemini = ScriptedClient(Provider.GEMINI, [_ok(Provider.GEMINI, GEMINI_FLASH_MODEL)])
    groq = ScriptedClient(Provider.GROQ, [])
    router, _, _ = _router({Provider.GROQ: groq, Provider.GEMINI: gemini})
    result = await router.route("agentic_tools", "frame", MESSAGES)
    assert result.provider is Provider.GEMINI
    assert len(gemini.calls) == 1
