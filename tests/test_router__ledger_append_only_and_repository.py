"""Router-ledger tests: append-only schema triggers + exact repository math.

Attacks the real 0003 migration on a throwaway database: UPDATE/DELETE must
abort (tamper-evidence, like audit_log), CHECK constraints must reject
nonsense rows, and the repository's cost summation must be EXACT Decimal —
never a float hop (zero-numerical-error rule, claude.md §3.11).
"""

import sqlite3
from decimal import Decimal
from pathlib import Path

import aiosqlite
import pytest

from engine.router.router_ledger_repository import (
    RouterLedgerEntry,
    insert_router_ledger_entry,
    recent_router_ledger_entries,
    summarize_router_ledger_by_provider,
)
from engine.storage import apply_migrations, open_sqlite_connection


async def _migrated_connection(
    tmp_db_path: Path, real_migrations_dir: Path
) -> aiosqlite.Connection:
    await apply_migrations(tmp_db_path, real_migrations_dir)
    return await open_sqlite_connection(tmp_db_path)


def _entry(
    provider: str = "groq",
    cost: str = "0.0000985",
    outcome: str = "ok",
    error_class: str | None = None,
    latency_ms: int = 450,
) -> RouterLedgerEntry:
    return RouterLedgerEntry(
        ts="2026-07-06T00:00:00+00:00",
        task_type="live_extraction",
        provider=provider,
        model="llama-3.3-70b-versatile",
        latency_ms=latency_ms,
        prompt_tokens=100,
        completion_tokens=50,
        est_cost_usd=Decimal(cost),
        outcome=outcome,
        error_class=error_class,
    )


# ---------------------------------------------------------------------------
# Append-only triggers (the tamper-evidence invariant)
# ---------------------------------------------------------------------------


async def test_inserts_are_allowed_appending_is_the_point(
    tmp_db_path: Path, real_migrations_dir: Path
) -> None:
    conn = await _migrated_connection(tmp_db_path, real_migrations_dir)
    try:
        await insert_router_ledger_entry(conn, _entry())
        await insert_router_ledger_entry(conn, _entry(provider="gemini"))
        rows = await recent_router_ledger_entries(conn)
        assert [r.provider for r in rows] == ["gemini", "groq"]  # newest first
    finally:
        await conn.close()


async def test_update_aborts_and_leaves_rows_intact(
    tmp_db_path: Path, real_migrations_dir: Path
) -> None:
    """Cost-history rewrite attempt: UPDATE must abort AND change nothing."""
    conn = await _migrated_connection(tmp_db_path, real_migrations_dir)
    try:
        await insert_router_ledger_entry(conn, _entry(cost="0.5"))
        with pytest.raises(sqlite3.DatabaseError, match="append-only"):
            await conn.execute("UPDATE router_ledger SET est_cost_usd = '0'")
        rows = await recent_router_ledger_entries(conn)
        assert rows[0].est_cost_usd == Decimal("0.5")  # untouched, to the unit
    finally:
        await conn.close()


async def test_delete_aborts_and_removes_nothing(
    tmp_db_path: Path, real_migrations_dir: Path
) -> None:
    conn = await _migrated_connection(tmp_db_path, real_migrations_dir)
    try:
        await insert_router_ledger_entry(conn, _entry())
        with pytest.raises(sqlite3.DatabaseError, match="append-only"):
            await conn.execute("DELETE FROM router_ledger")
        with pytest.raises(sqlite3.DatabaseError, match="append-only"):
            await conn.execute("DELETE FROM router_ledger WHERE id = 1")
        assert len(await recent_router_ledger_entries(conn)) == 1
    finally:
        await conn.close()


async def test_failed_tamper_does_not_block_further_appends(
    tmp_db_path: Path, real_migrations_dir: Path
) -> None:
    conn = await _migrated_connection(tmp_db_path, real_migrations_dir)
    try:
        await insert_router_ledger_entry(conn, _entry())
        with pytest.raises(sqlite3.DatabaseError):
            await conn.execute("DELETE FROM router_ledger")
        await insert_router_ledger_entry(conn, _entry(provider="gemini"))
        assert len(await recent_router_ledger_entries(conn)) == 2
    finally:
        await conn.close()


async def test_both_guard_triggers_exist_in_the_schema(
    tmp_db_path: Path, real_migrations_dir: Path
) -> None:
    """The invariant lives in the schema; a future migration must not be
    able to drop it silently."""
    conn = await _migrated_connection(tmp_db_path, real_migrations_dir)
    try:
        cursor = await conn.execute(
            "SELECT name FROM sqlite_master WHERE type='trigger' AND tbl_name='router_ledger'"
        )
        names = {str(row[0]) for row in await cursor.fetchall()}
        await cursor.close()
    finally:
        await conn.close()
    assert {"router_ledger_block_update", "router_ledger_block_delete"} <= names


# ---------------------------------------------------------------------------
# CHECK constraints (deny nonsense rows in the schema itself)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("column", "value"),
    [("latency_ms", -1), ("prompt_tokens", -1), ("completion_tokens", -1)],
)
async def test_negative_counters_are_rejected_by_the_schema(
    tmp_db_path: Path, real_migrations_dir: Path, column: str, value: int
) -> None:
    conn = await _migrated_connection(tmp_db_path, real_migrations_dir)
    try:
        overrides = {"latency_ms": 1, "prompt_tokens": 1, "completion_tokens": 1}
        overrides[column] = value
        with pytest.raises(sqlite3.IntegrityError):
            await conn.execute(
                "INSERT INTO router_ledger (ts, task_type, provider, model, latency_ms,"
                " prompt_tokens, completion_tokens, est_cost_usd, outcome, error_class)"
                " VALUES ('t', 'x', 'groq', 'm', ?, ?, ?, '0', 'ok', NULL)",
                (
                    overrides["latency_ms"],
                    overrides["prompt_tokens"],
                    overrides["completion_tokens"],
                ),
            )
    finally:
        await conn.close()


@pytest.mark.parametrize(
    ("outcome", "error_class"),
    [("success", None), ("OK", None), ("ok", "mystery"), ("error", "5xx")],
)
async def test_outcome_and_error_class_vocabulary_is_schema_enforced(
    tmp_db_path: Path, real_migrations_dir: Path, outcome: str, error_class: str | None
) -> None:
    conn = await _migrated_connection(tmp_db_path, real_migrations_dir)
    try:
        with pytest.raises(sqlite3.IntegrityError):
            await conn.execute(
                "INSERT INTO router_ledger (ts, task_type, provider, model, latency_ms,"
                " prompt_tokens, completion_tokens, est_cost_usd, outcome, error_class)"
                " VALUES ('t', 'x', 'groq', 'm', 1, 1, 1, '0', ?, ?)",
                (outcome, error_class),
            )
    finally:
        await conn.close()


# ---------------------------------------------------------------------------
# Repository summaries: exact Decimal money, correct aggregates
# ---------------------------------------------------------------------------


async def test_summary_sums_costs_in_exact_decimal_never_float(
    tmp_db_path: Path, real_migrations_dir: Path
) -> None:
    """0.1 + 0.2 is the canonical float trap: as floats the sum is
    0.30000000000000004; the ledger must produce EXACTLY 0.3."""
    conn = await _migrated_connection(tmp_db_path, real_migrations_dir)
    try:
        await insert_router_ledger_entry(conn, _entry(cost="0.1"))
        await insert_router_ledger_entry(conn, _entry(cost="0.2"))
        (summary,) = await summarize_router_ledger_by_provider(conn)
        assert summary.total_cost_usd == Decimal("0.3")  # exact, to the unit
        assert str(summary.total_cost_usd) == "0.3"  # and no float residue
    finally:
        await conn.close()


async def test_summary_aggregates_per_provider_boundary_exact(
    tmp_db_path: Path, real_migrations_dir: Path
) -> None:
    conn = await _migrated_connection(tmp_db_path, real_migrations_dir)
    try:
        await insert_router_ledger_entry(conn, _entry(provider="groq", latency_ms=100))
        await insert_router_ledger_entry(conn, _entry(provider="groq", latency_ms=300))
        await insert_router_ledger_entry(
            conn,
            _entry(provider="groq", cost="0", outcome="error", error_class="timeout"),
        )
        await insert_router_ledger_entry(conn, _entry(provider="gemini", cost="0.000045"))
        summaries = {s.provider: s for s in await summarize_router_ledger_by_provider(conn)}
        groq = summaries["groq"]
        assert (groq.total_calls, groq.ok_calls, groq.error_calls) == (3, 2, 1)
        assert groq.prompt_tokens == 300 and groq.completion_tokens == 150
        assert groq.total_cost_usd == Decimal("0.0000985") * 2
        gemini = summaries["gemini"]
        assert (gemini.total_calls, gemini.ok_calls, gemini.error_calls) == (1, 1, 0)
        assert gemini.total_cost_usd == Decimal("0.000045")
    finally:
        await conn.close()


async def test_recent_entries_round_trip_every_field_exactly(
    tmp_db_path: Path, real_migrations_dir: Path
) -> None:
    conn = await _migrated_connection(tmp_db_path, real_migrations_dir)
    try:
        original = _entry(outcome="error", error_class="ratelimit", cost="0")
        await insert_router_ledger_entry(conn, original)
        (loaded,) = await recent_router_ledger_entries(conn)
        assert loaded == original  # dataclass equality: every field, exact
    finally:
        await conn.close()


async def test_recent_entries_limit_is_respected(
    tmp_db_path: Path, real_migrations_dir: Path
) -> None:
    conn = await _migrated_connection(tmp_db_path, real_migrations_dir)
    try:
        for _ in range(5):
            await insert_router_ledger_entry(conn, _entry())
        assert len(await recent_router_ledger_entries(conn, limit=3)) == 3
    finally:
        await conn.close()
