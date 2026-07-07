"""Measure the tri-provider router: Decimal-exact cost + fallback behaviour.

Two deterministic, network-free measurements against the REAL router code:

  * COST EXACTNESS — engine.router.estimate_cost_usd is verified against an
    INDEPENDENT exact rational (fractions.Fraction) computation across a grid of
    token counts and every priced model. A match to the last digit proves the
    money path carries zero floating-point error (CLAUDE.md 3.11: a single
    arithmetic error on a deterministic path is unacceptable). Per-task-type
    example costs are derived from the real routing table's resolved primary.

  * FALLBACK MATRIX — the real ProviderRouter is driven with scripted fake
    clients (the same ScriptedClient/RecordingLedger pattern the unit suite
    uses) to record, per error class, whether it retries, how long it backs off,
    and where it cascades. No SDKs, no network, no keys.
"""

from __future__ import annotations

import asyncio
import json
from decimal import Decimal
from fractions import Fraction
from pathlib import Path
from typing import Any

from engine.router.completion_contract import (
    ChatMessage,
    CompletionRequest,
    Provider,
    ProviderCompletion,
    ProviderCompletionClient,
)
from engine.router.fallback_executor import RATELIMIT_RETRY_DELAY_SECONDS, ProviderRouter
from engine.router.model_pricing import MODEL_PRICES_USD_PER_MILLION, estimate_cost_usd
from engine.router.router_errors import ProviderCallError, ProviderErrorClass
from engine.router.router_ledger_repository import RouterLedgerEntry
from engine.router.routing_table import resolve_route

_DATA_DIR = Path(__file__).resolve().parent.parent / "data"
_MESSAGES = (ChatMessage(role="user", content="transcript excerpt (data)"),)
_TOKEN_GRID = ((0, 0), (1, 1), (100, 50), (1_000, 500), (8_000, 2_000), (128_000, 4_096))
_TASK_TYPES = (
    "live_extraction",
    "intent_parsing",
    "enhanced_notes",
    "ask_synthesis",
    "long_context_bulk",
    "agentic_tools",
    "dictation_cleanup",
)


def _fraction_cost(model: str, prompt: int, completion: int) -> Fraction:
    """Independent exact cost via rationals — a different arithmetic path."""
    in_price, out_price = MODEL_PRICES_USD_PER_MILLION[model]
    return (
        Fraction(prompt) * Fraction(str(in_price)) + Fraction(completion) * Fraction(str(out_price))
    ) / Fraction(1_000_000)


def _measure_cost() -> dict[str, Any]:
    grid: list[dict[str, Any]] = []
    mismatches = 0
    for model in sorted(MODEL_PRICES_USD_PER_MILLION):
        for prompt, completion in _TOKEN_GRID:
            got = estimate_cost_usd(model, prompt, completion)
            expected = _fraction_cost(model, prompt, completion)
            exact = Fraction(got) == expected  # Decimal -> exact Fraction, no rounding
            mismatches += 0 if exact else 1
            grid.append(
                {
                    "model": model,
                    "prompt_tokens": prompt,
                    "completion_tokens": completion,
                    "cost_usd": str(got),
                    "matches_rational": exact,
                }
            )
    price_table = {
        model: {"input_usd_per_million": str(prices[0]), "output_usd_per_million": str(prices[1])}
        for model, prices in MODEL_PRICES_USD_PER_MILLION.items()
    }
    # Per-task example cost using the resolved primary in the fully-keyed world.
    keyed = frozenset({"groq", "gemini", "anthropic"})
    task_examples: list[dict[str, Any]] = []
    for task in _TASK_TYPES:
        route = resolve_route(task, keyed)
        primary = route.attempts[0]
        cost = estimate_cost_usd(primary.model, 4_000, 800)
        task_examples.append(
            {
                "task_type": task,
                "primary_provider": primary.provider.value,
                "primary_model": primary.model,
                "latency_budget_p95_ms": route.latency_budget_p95_ms,
                "example_cost_usd_4000in_800out": str(cost),
            }
        )
    return {
        "price_table_usd_per_million": price_table,
        "grid_points": len(grid),
        "rational_mismatches": mismatches,
        "cost_grid": grid,
        "task_type_examples_keyed_world": task_examples,
    }


class _ScriptedClient(ProviderCompletionClient):
    """Replays scripted outcomes in order — mirrors the unit-suite fake."""

    def __init__(
        self, provider: Provider, script: list[ProviderCompletion | ProviderCallError]
    ) -> None:
        self.provider = provider
        self._script = list(script)
        self.calls: list[CompletionRequest] = []

    async def complete(self, request: CompletionRequest) -> ProviderCompletion:
        self.calls.append(request)
        outcome = self._script.pop(0)
        if isinstance(outcome, ProviderCallError):
            raise outcome
        return outcome


class _RecordingLedger:
    def __init__(self) -> None:
        self.entries: list[RouterLedgerEntry] = []

    async def record(self, entry: RouterLedgerEntry) -> None:
        self.entries.append(entry)


class _RecordingSleep:
    def __init__(self) -> None:
        self.delays: list[float] = []

    async def __call__(self, seconds: float) -> None:
        self.delays.append(seconds)


def _ok(provider: Provider, model: str) -> ProviderCompletion:
    return ProviderCompletion(
        text="ok", provider=provider, model=model, prompt_tokens=100, completion_tokens=50
    )


def _err(provider: Provider, model: str, klass: ProviderErrorClass) -> ProviderCallError:
    return ProviderCallError(
        provider=provider.value, model=model, error_class=klass, message=f"synthetic {klass}"
    )


async def _measure_fallback() -> list[dict[str, Any]]:
    from engine.router.routing_table import GEMINI_FLASH_MODEL, GROQ_FAST_MODEL

    scenarios: list[tuple[str, list[ProviderCompletion | ProviderCallError]]] = [
        ("primary_first_try", [_ok(Provider.GROQ, GROQ_FAST_MODEL)]),
        (
            "timeout_retry_then_ok",
            [_err(Provider.GROQ, GROQ_FAST_MODEL, ProviderErrorClass.TIMEOUT),
             _ok(Provider.GROQ, GROQ_FAST_MODEL)],
        ),
        (
            "ratelimit_backoff_then_ok",
            [_err(Provider.GROQ, GROQ_FAST_MODEL, ProviderErrorClass.RATELIMIT),
             _ok(Provider.GROQ, GROQ_FAST_MODEL)],
        ),
        (
            "auth_no_retry_cascade",
            [_err(Provider.GROQ, GROQ_FAST_MODEL, ProviderErrorClass.AUTH)],
        ),
        (
            "double_server_cascade",
            [_err(Provider.GROQ, GROQ_FAST_MODEL, ProviderErrorClass.SERVER),
             _err(Provider.GROQ, GROQ_FAST_MODEL, ProviderErrorClass.SERVER)],
        ),
    ]
    results: list[dict[str, Any]] = []
    for name, groq_script in scenarios:
        groq = _ScriptedClient(Provider.GROQ, groq_script)
        gemini = _ScriptedClient(Provider.GEMINI, [_ok(Provider.GEMINI, GEMINI_FLASH_MODEL)])
        ledger = _RecordingLedger()
        sleep = _RecordingSleep()
        router = ProviderRouter(
            {Provider.GROQ: groq, Provider.GEMINI: gemini}, ledger.record, sleep=sleep
        )
        routed = await router.route("live_extraction", "frame", _MESSAGES)
        results.append(
            {
                "scenario": name,
                "final_provider": routed.provider.value,
                "final_model": routed.model,
                "total_attempts": routed.attempts,
                "groq_calls": len(groq.calls),
                "gemini_calls": len(gemini.calls),
                "backoff_delays_s": list(sleep.delays),
                "ledger_outcomes": [e.outcome for e in ledger.entries],
                "failed_rows_cost_zero": all(
                    e.est_cost_usd == Decimal(0) for e in ledger.entries if e.outcome == "error"
                ),
            }
        )
    return results


def main() -> None:
    cost = _measure_cost()
    fallback = asyncio.run(_measure_fallback())
    result = {
        "component": "engine.router (real ProviderRouter, model_pricing, routing_table)",
        "cost": cost,
        "ratelimit_backoff_seconds": RATELIMIT_RETRY_DELAY_SECONDS,
        "fallback_matrix": fallback,
    }
    _DATA_DIR.mkdir(parents=True, exist_ok=True)
    out = _DATA_DIR / "router_cost_and_fallback.json"
    out.write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")
    print(f"wrote {out}")
    print(
        f"  cost grid points={cost['grid_points']}  "
        f"rational mismatches={cost['rational_mismatches']}"
    )
    print(f"  fallback scenarios measured={len(fallback)}")


if __name__ == "__main__":
    main()
