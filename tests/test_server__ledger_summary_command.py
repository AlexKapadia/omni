"""M7 ledger.summary surface: the real router cost/latency view.

Adversarial coverage: real ledger rows aggregate per provider AND per task;
costs are EXACT decimal STRINGS (no float drift) end to end; grand totals
sum in Decimal; the recent feed is newest-first and limit-bounded; and the
limit payload deny-by-default rejects out-of-range windows.
"""

import uuid
from decimal import Decimal
from pathlib import Path

from engine.protocol import Envelope, EnvelopeKind
from engine.router.router_ledger_repository import RouterLedgerEntry, insert_router_ledger_entry
from engine.storage.sqlite_connection import open_sqlite_connection
from engine.storage.sqlite_migrations_runner import apply_migrations
from engine.wiring.ledger_summary_command_dispatcher import (
    LedgerSummaryCommandGateway,
    dispatch_ledger_command,
)


class _Collector:
    def __init__(self) -> None:
        self.sent: list[Envelope] = []

    async def __call__(self, envelope: Envelope) -> None:
        self.sent.append(envelope)


def _command(payload: dict[str, object]) -> Envelope:
    return Envelope(
        v=1, kind=EnvelopeKind.COMMAND, name="ledger.summary", id=str(uuid.uuid4()), payload=payload
    )


def _entry(provider: str, task: str, cost: str, ts: str) -> RouterLedgerEntry:
    return RouterLedgerEntry(
        ts=ts,
        task_type=task,
        provider=provider,
        model=f"{provider}-model",
        latency_ms=500,
        prompt_tokens=100,
        completion_tokens=20,
        est_cost_usd=Decimal(cost),
        outcome="ok",
        error_class=None,
    )


async def _seed(db_path: Path, migrations: Path, entries: list[RouterLedgerEntry]) -> None:
    await apply_migrations(db_path, migrations)
    connection = await open_sqlite_connection(db_path)
    try:
        for entry in entries:
            await insert_router_ledger_entry(connection, entry)
    finally:
        await connection.close()


async def test_summary_reports_provider_task_and_exact_decimal_totals(
    tmp_path: Path, real_migrations_dir: Path
) -> None:
    db = tmp_path / "omni.db"
    # Costs chosen so a float sum would drift (0.1 + 0.2 != 0.3 in binary).
    await _seed(
        db,
        real_migrations_dir,
        [
            _entry("groq", "intent_parsing", "0.10", "2026-07-01T00:00:00+00:00"),
            _entry("gemini", "note_enhancement", "0.20", "2026-07-01T00:01:00+00:00"),
            _entry("groq", "note_enhancement", "0.05", "2026-07-01T00:02:00+00:00"),
        ],
    )
    gateway = LedgerSummaryCommandGateway(db_path=db, migrations_dir=real_migrations_dir)
    send = _Collector()
    await dispatch_ledger_command(_command({}), gateway, send)
    payload = send.sent[0].payload

    by_provider = {row["provider"]: row for row in payload["by_provider"]}
    assert by_provider["groq"]["total_cost_usd"] == "0.15"  # exact string, no float hop
    assert by_provider["gemini"]["total_cost_usd"] == "0.20"
    by_task = {row["task"]: row for row in payload["by_task"]}
    assert set(by_task) == {"intent_parsing", "note_enhancement"}
    assert by_task["note_enhancement"]["total_calls"] == 2
    # Grand total is the exact Decimal sum across the whole ledger.
    assert payload["totals"]["total_cost_usd"] == "0.35"
    assert payload["totals"]["total_calls"] == 3


async def test_recent_feed_is_newest_first_and_limit_bounded(
    tmp_path: Path, real_migrations_dir: Path
) -> None:
    db = tmp_path / "omni.db"
    await _seed(
        db,
        real_migrations_dir,
        [
            _entry("groq", "intent_parsing", "0.01", f"2026-07-01T00:0{i}:00+00:00")
            for i in range(5)
        ],
    )
    gateway = LedgerSummaryCommandGateway(db_path=db, migrations_dir=real_migrations_dir)
    send = _Collector()
    await dispatch_ledger_command(_command({"limit": 2}), gateway, send)
    recent = send.sent[0].payload["recent"]
    assert len(recent) == 2  # limit honoured
    # Newest first: id DESC => the last-inserted ts leads.
    assert recent[0]["ts"] == "2026-07-01T00:04:00+00:00"
    assert recent[0]["est_cost_usd"] == "0.01"  # exact string in the feed too


async def test_out_of_range_limit_is_refused(tmp_path: Path, real_migrations_dir: Path) -> None:
    gateway = LedgerSummaryCommandGateway(
        db_path=tmp_path / "omni.db", migrations_dir=real_migrations_dir
    )
    send = _Collector()
    await dispatch_ledger_command(_command({"limit": 100_000}), gateway, send)
    # Deny by default: a hostile unbounded window is rejected at the payload.
    assert send.sent[0].name == "error"


async def test_empty_ledger_returns_zeroed_totals(
    tmp_path: Path, real_migrations_dir: Path
) -> None:
    gateway = LedgerSummaryCommandGateway(
        db_path=tmp_path / "omni.db", migrations_dir=real_migrations_dir
    )
    send = _Collector()
    await dispatch_ledger_command(_command({}), gateway, send)
    payload = send.sent[0].payload
    assert payload["by_provider"] == []
    assert payload["totals"] == {
        "total_calls": 0,
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_cost_usd": "0",
    }
