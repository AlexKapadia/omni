"""Bounded REAL provider sample: cost + latency of the live router.

This is the one non-hermetic harness. It makes a small, metered number of REAL
calls through Omni's ProviderRouter to the actual providers, so the evidence
carries genuine end-to-end cost and latency — not just the deterministic
arithmetic. It is fail-closed and honest:

  * Keys are read from .env by THIS harness (the engine never reads .env) and
    injected into the provider key store. Key values are never printed, logged,
    or written to the output — only the boolean 'keyed' fact and the resulting
    cost/latency numbers leave this process.
  * An ABSOLUTE spend cap of $0.50 (Decimal) bounds the run; each planned call
    is skipped once the measured cumulative cost would approach the cap. Inputs
    are tiny and max_tokens is small, so real spend is a fraction of a cent.
  * The REAL total cost is reported exactly as measured (including any overshoot).
  * With no keys, it writes an honest 'skipped, real_spend=$0.00' record.
"""

from __future__ import annotations

import asyncio
import json
import os
from decimal import Decimal
from pathlib import Path
from typing import Any

from engine.router.completion_contract import ChatMessage, Provider, ProviderCompletionClient
from engine.router.fallback_executor import ProviderRouter
from engine.router.model_pricing import estimate_cost_usd
from engine.router.provider_client_registry import build_provider_clients
from engine.router.router_ledger_repository import RouterLedgerEntry
from engine.security.provider_key_store import ProviderKeyStore
from statistics_helpers import nearest_rank_percentile_ms

_DATA_DIR = Path(__file__).resolve().parent.parent / "data"
_ENV_PATH = Path("C:/dev/Omni/.env")
_ABSOLUTE_CAP_USD = Decimal("0.50")  # hard ceiling on total real spend
_MAX_TOKENS = 64  # tiny outputs keep each call ~$0.0002

# Cheap, Groq-primary task types with tiny realistic inputs.
_PLAN: tuple[tuple[str, str, str], ...] = (
    ("live_extraction", "Extract action items as short JSON.",
     "We agreed Priya sends the deck by Friday and Marcus reviews the migration."),
    ("dictation_cleanup", "Return {\"cleaned\": \"...\"} removing fillers only.",
     "um so the the plan is to ship on friday i think"),
    ("intent_parsing", "Classify the intent in one short phrase.",
     "schedule a follow up with the design team next week"),
)
_ROUNDS = 5  # 3 task types x 5 rounds = up to 15 real calls


def _load_env_keys() -> frozenset[str]:
    """Inject GROQ/GEMINI/ANTHROPIC keys from .env into os.environ. Never printed."""
    injected: set[str] = set()
    if not _ENV_PATH.is_file():
        return frozenset()
    for line in _ENV_PATH.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        name, value = stripped.split("=", 1)
        name = name.strip()
        value = value.strip().strip('"').strip("'")
        if name in ("GROQ_API_KEY", "GEMINI_API_KEY", "ANTHROPIC_API_KEY") and value:
            os.environ[name] = value  # value stays in-process, never emitted
            injected.add(name.removesuffix("_API_KEY").lower())
    return frozenset(injected)


class _MeteringLedger:
    """Captures each attempt's cost/latency; running total drives the cap."""

    def __init__(self) -> None:
        self.entries: list[RouterLedgerEntry] = []
        self.total_cost = Decimal(0)

    async def record(self, entry: RouterLedgerEntry) -> None:
        self.entries.append(entry)
        self.total_cost += entry.est_cost_usd


async def _run() -> dict[str, Any]:
    keyed = _load_env_keys()
    if "groq" not in keyed and "gemini" not in keyed:
        return {
            "status": "skipped",
            "reason": "no GROQ/GEMINI keys available in .env",
            "keyed_providers": sorted(keyed),
            "real_total_spend_usd": "0",
        }

    clients: dict[Provider, ProviderCompletionClient] = build_provider_clients(ProviderKeyStore())
    ledger = _MeteringLedger()
    router = ProviderRouter(clients, ledger.record)

    calls: list[dict[str, Any]] = []
    latencies_ms: list[float] = []
    failures: list[str] = []
    fallbacks = 0

    for _ in range(_ROUNDS):
        for task_type, frame, content in _PLAN:
            # Fail-closed on the budget: stop before a call could breach the cap.
            headroom = estimate_cost_usd("claude-sonnet-4-5", 4000, _MAX_TOKENS)
            projected = ledger.total_cost + headroom
            if projected > _ABSOLUTE_CAP_USD:
                failures.append(f"cap reached before {task_type}; stopping")
                break
            try:
                routed = await router.route(
                    task_type, frame, (ChatMessage(role="user", content=content),),
                    max_tokens=_MAX_TOKENS,
                )
            except Exception as exc:  # network / provider errors: record, keep going
                failures.append(f"{task_type}: {type(exc).__name__}")
                continue
            if routed.attempts > 1:
                fallbacks += 1
            latencies_ms.append(float(routed.latency_ms))
            calls.append(
                {
                    "task_type": task_type,
                    "provider": routed.provider.value,
                    "model": routed.model,
                    "latency_ms": routed.latency_ms,
                    "attempts": routed.attempts,
                    "prompt_tokens": routed.completion.prompt_tokens,
                    "completion_tokens": routed.completion.completion_tokens,
                    "cost_usd": str(
                        estimate_cost_usd(
                            routed.model,
                            routed.completion.prompt_tokens,
                            routed.completion.completion_tokens,
                        )
                    ),
                }
            )
        else:
            continue
        break

    by_provider: dict[str, dict[str, Any]] = {}
    for entry in ledger.entries:
        bucket = by_provider.setdefault(
            entry.provider, {"calls": 0, "cost_usd": Decimal(0), "latency_ms": []}
        )
        bucket["calls"] = int(bucket["calls"]) + 1
        bucket["cost_usd"] = Decimal(str(bucket["cost_usd"])) + entry.est_cost_usd
        lat_list = bucket["latency_ms"]
        if isinstance(lat_list, list):
            lat_list.append(entry.latency_ms)
    provider_summary = {
        prov: {
            "calls": info["calls"],
            "total_cost_usd": str(info["cost_usd"]),
            "mean_latency_ms": (
                sum(info["latency_ms"]) / len(info["latency_ms"])
                if info["latency_ms"]
                else None
            ),
        }
        for prov, info in by_provider.items()
    }

    return {
        "status": "measured",
        "provider": "REAL provider calls via engine.router.ProviderRouter",
        "keyed_providers": sorted(keyed),
        "absolute_cap_usd": str(_ABSOLUTE_CAP_USD),
        "successful_calls": len(calls),
        "ledger_attempts": len(ledger.entries),
        "fallbacks_triggered": fallbacks,
        "call_failures": failures,
        "real_total_spend_usd": str(ledger.total_cost),
        "overshot_cap": ledger.total_cost > _ABSOLUTE_CAP_USD,
        "latency_ms": {
            "p50": nearest_rank_percentile_ms(latencies_ms, 50) if latencies_ms else None,
            "p95": nearest_rank_percentile_ms(latencies_ms, 95) if latencies_ms else None,
            "raw_ms": latencies_ms,
        },
        "by_provider": provider_summary,
        "calls": calls,
    }


def main() -> None:
    result = asyncio.run(_run())
    _DATA_DIR.mkdir(parents=True, exist_ok=True)
    out = _DATA_DIR / "router_live_sample.json"
    out.write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")
    print(f"wrote {out}")
    if result["status"] == "measured":
        print(
            f"  REAL calls={result['successful_calls']}  "
            f"total spend=${result['real_total_spend_usd']}  "
            f"fallbacks={result['fallbacks_triggered']}"
        )
    else:
        print(f"  {result['status']}: {result.get('reason')}")


if __name__ == "__main__":
    main()
