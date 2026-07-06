"""Repository for ``router_ledger`` rows: every external model call, logged.

Purpose: the only place router-ledger rows are written and summarised. One
row per provider ATTEMPT (successes and failures alike) — latency, exact
token counts, exact cost, outcome — feeding the Settings screen's live
cost/latency view (speed is a showcase feature) and the audit posture.
Pipeline position: called by ``engine.router.fallback_executor`` after
every attempt; read by the Settings API.

Correctness / security invariants:
- ``est_cost_usd`` is stored as an EXACT decimal STRING and summed in
  Python ``Decimal`` — float arithmetic never touches the money path
  (zero-numerical-error rule, claude.md §3.11).
- The table is append-only (schema triggers, like ``audit_log``); this
  repository only ever INSERTs and SELECTs.
- All values are bound as SQL parameters (injection defence), and error
  messages arriving here were already key-redacted at the client boundary.
"""

from dataclasses import dataclass
from decimal import Decimal

import aiosqlite


@dataclass(frozen=True)
class RouterLedgerEntry:
    """One provider attempt, exactly as it will be persisted."""

    ts: str  # ISO-8601 UTC
    task_type: str
    provider: str
    model: str
    latency_ms: int
    prompt_tokens: int
    completion_tokens: int
    est_cost_usd: Decimal
    outcome: str  # 'ok' | 'error'
    error_class: str | None  # taxonomy value when outcome='error', else None


@dataclass(frozen=True)
class ProviderLedgerSummary:
    """Per-provider aggregates for the Settings screen."""

    provider: str
    total_calls: int
    ok_calls: int
    error_calls: int
    prompt_tokens: int
    completion_tokens: int
    total_cost_usd: Decimal
    avg_latency_ms: float


async def insert_router_ledger_entry(
    connection: aiosqlite.Connection, entry: RouterLedgerEntry
) -> None:
    """Append one attempt row. Parameterised only; cost as exact string."""
    await connection.execute(
        "INSERT INTO router_ledger "
        "(ts, task_type, provider, model, latency_ms, prompt_tokens, "
        " completion_tokens, est_cost_usd, outcome, error_class) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            entry.ts,
            entry.task_type,
            entry.provider,
            entry.model,
            entry.latency_ms,
            entry.prompt_tokens,
            entry.completion_tokens,
            # Exactness invariant: serialise the Decimal, never float().
            str(entry.est_cost_usd),
            entry.outcome,
            entry.error_class,
        ),
    )


async def summarize_router_ledger_by_provider(
    connection: aiosqlite.Connection,
) -> list[ProviderLedgerSummary]:
    """Aggregate the ledger per provider.

    Counts/tokens/latency aggregate in SQL; COST is summed in Python
    ``Decimal`` from the exact stored strings — SQLite's SUM would coerce
    to float and violate the zero-numerical-error rule.
    """
    cursor = await connection.execute(
        "SELECT provider, "
        "       COUNT(*), "
        "       SUM(CASE WHEN outcome = 'ok' THEN 1 ELSE 0 END), "
        "       SUM(CASE WHEN outcome = 'error' THEN 1 ELSE 0 END), "
        "       SUM(prompt_tokens), "
        "       SUM(completion_tokens), "
        "       AVG(latency_ms) "
        "FROM router_ledger GROUP BY provider ORDER BY provider"
    )
    aggregate_rows = await cursor.fetchall()
    await cursor.close()
    cursor = await connection.execute("SELECT provider, est_cost_usd FROM router_ledger")
    cost_rows = await cursor.fetchall()
    await cursor.close()
    cost_by_provider: dict[str, Decimal] = {}
    for provider, cost_text in cost_rows:
        # Decimal(text) reproduces the stored value exactly — no float hop.
        cost_by_provider[str(provider)] = cost_by_provider.get(
            str(provider), Decimal(0)
        ) + Decimal(str(cost_text))
    return [
        ProviderLedgerSummary(
            provider=str(row[0]),
            total_calls=int(row[1]),
            ok_calls=int(row[2]),
            error_calls=int(row[3]),
            prompt_tokens=int(row[4]),
            completion_tokens=int(row[5]),
            total_cost_usd=cost_by_provider.get(str(row[0]), Decimal(0)),
            avg_latency_ms=float(row[6]),
        )
        for row in aggregate_rows
    ]


async def recent_router_ledger_entries(
    connection: aiosqlite.Connection, limit: int = 50
) -> list[RouterLedgerEntry]:
    """Most-recent attempts, newest first (the Settings live-latency feed)."""
    cursor = await connection.execute(
        "SELECT ts, task_type, provider, model, latency_ms, prompt_tokens, "
        "       completion_tokens, est_cost_usd, outcome, error_class "
        "FROM router_ledger ORDER BY id DESC LIMIT ?",
        (limit,),
    )
    rows = await cursor.fetchall()
    await cursor.close()
    return [
        RouterLedgerEntry(
            ts=str(row[0]),
            task_type=str(row[1]),
            provider=str(row[2]),
            model=str(row[3]),
            latency_ms=int(row[4]),
            prompt_tokens=int(row[5]),
            completion_tokens=int(row[6]),
            est_cost_usd=Decimal(str(row[7])),
            outcome=str(row[8]),
            error_class=None if row[9] is None else str(row[9]),
        )
        for row in rows
    ]
