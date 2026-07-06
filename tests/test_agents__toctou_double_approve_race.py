"""TOCTOU / exactly-once execution tests: two executors, one card, one action.

Security invariant under test (approval-before-execute + exactly-once):
the executor's transactional claim means a card in 'approved' executes
EXACTLY once no matter how many executors race it, and a card in any
other status is refused with a typed error — the status re-check happens
at the row level INSIDE the claim transaction, not from a stale read.
"""

import asyncio
from pathlib import Path

import pytest

from engine.agents.agents_errors import CardNotExecutableError
from engine.agents.approval_card_types import CardType
from engine.agents.approval_cards_repository import claim_card_for_execution
from engine.agents.card_executor import execute_approved_card
from engine.agents.tool_registry import AgentTool, ToolRegistry, ToolResult
from engine.agents.vault_write_note_tool import VaultWriteNoteParams
from engine.storage import open_sqlite_connection
from tests.agents_test_support import (
    TS,
    FakeGoogleSession,
    approved_card,
    audit_rows,
    card_status,
    migrated_connection,
)


class CountingTool(AgentTool):
    """A write_note tool that counts real executions (the race detector)."""

    name = "counting_tool"
    card_type = CardType.WRITE_NOTE
    params_model = VaultWriteNoteParams
    description = "counts executions"

    def __init__(self) -> None:
        self.executions = 0

    def dry_run(self, params: object) -> tuple[str, ...]:
        return ("counting",)

    async def execute(self, params: object, google_session: object) -> ToolResult:
        self.executions += 1
        await asyncio.sleep(0)  # yield, widening any race window
        return ToolResult(summary_line="counted")


async def test_two_racing_executors_one_card_exactly_one_executes(
    tmp_db_path: Path, real_migrations_dir: Path
) -> None:
    """The core race: two independent connections execute the same approved
    card concurrently. Exactly one tool run, exactly one audit row from the
    winner, a typed refusal for the loser, final status 'executed'."""
    setup = await migrated_connection(tmp_db_path, real_migrations_dir)
    try:
        card_id = await approved_card(setup)
    finally:
        await setup.close()

    tool = CountingTool()
    registry = ToolRegistry((tool,))
    conn_a = await open_sqlite_connection(tmp_db_path)
    conn_b = await open_sqlite_connection(tmp_db_path)
    try:
        results = await asyncio.gather(
            execute_approved_card(
                conn_a, card_id, registry=registry,
                google_session=FakeGoogleSession(), vault_root=None,
            ),
            execute_approved_card(
                conn_b, card_id, registry=registry,
                google_session=FakeGoogleSession(), vault_root=None,
            ),
            return_exceptions=True,
        )
        winners = [r for r in results if not isinstance(r, BaseException)]
        losers = [r for r in results if isinstance(r, BaseException)]
        assert len(winners) == 1, f"exactly one executor must win, got {results!r}"
        assert len(losers) == 1
        assert isinstance(losers[0], CardNotExecutableError)
        assert tool.executions == 1  # the action itself ran exactly once
        assert winners[0].final_status == "executed"
        assert await card_status(conn_a, card_id) == "executed"
        rows = await audit_rows(conn_a)
        assert len(rows) == 1  # one attempt -> one audit row; the loser wrote none
    finally:
        await conn_a.close()
        await conn_b.close()


@pytest.mark.parametrize("status", ["pending", "dismissed"])
async def test_unapproved_cards_are_refused_with_a_typed_error(
    tmp_db_path: Path, real_migrations_dir: Path, status: str
) -> None:
    conn = await migrated_connection(tmp_db_path, real_migrations_dir)
    try:
        cursor = await conn.execute(
            "INSERT INTO approval_cards"
            " (source, source_row_id, card_type, payload_json, status, created_at)"
            " VALUES ('dictation', 1, 'write_note', '{}', 'pending', ?)",
            (TS,),
        )
        card_id = int(cursor.lastrowid or 0)
        if status == "dismissed":
            await conn.execute(
                "UPDATE approval_cards SET status = 'dismissed', decided_at = ?"
                " WHERE id = ?",
                (TS, card_id),
            )
        tool = CountingTool()
        with pytest.raises(CardNotExecutableError) as excinfo:
            await execute_approved_card(
                conn, card_id, registry=ToolRegistry((tool,)),
                google_session=FakeGoogleSession(), vault_root=None,
            )
        assert excinfo.value.status == status  # the honest, current status
        assert tool.executions == 0  # nothing ran
        assert await audit_rows(conn) == []  # nothing to audit: nothing happened
    finally:
        await conn.close()


async def test_missing_card_is_refused(
    tmp_db_path: Path, real_migrations_dir: Path
) -> None:
    conn = await migrated_connection(tmp_db_path, real_migrations_dir)
    try:
        with pytest.raises(CardNotExecutableError, match="missing"):
            await execute_approved_card(
                conn, 424242, registry=ToolRegistry((CountingTool(),)),
                google_session=FakeGoogleSession(), vault_root=None,
            )
    finally:
        await conn.close()


async def test_repository_claim_is_single_winner_even_sequentially(
    tmp_db_path: Path, real_migrations_dir: Path
) -> None:
    """Claim-level check without the executor: second claim sees None."""
    conn = await migrated_connection(tmp_db_path, real_migrations_dir)
    try:
        card_id = await approved_card(conn)
        first = await claim_card_for_execution(conn, card_id)
        second = await claim_card_for_execution(conn, card_id)
        assert first is not None and first.status == "executing"
        assert second is None
    finally:
        await conn.close()
