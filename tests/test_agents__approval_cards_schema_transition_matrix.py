"""0008 approval_cards schema attack tests: the status machine is IN the schema.

Security invariant under test (approval-before-execute, claude.md §5.6):
only pending->approved|dismissed, approved->executing, and
executing->executed|failed may ever run. EVERY other (from, to) pair —
including pending->executed (skipping approval), executed->anything
(history rewrite), and dismissed->approved (resurrecting a refusal) — must
abort AT THE SQL LAYER, and the row must survive untouched. These tests
attack the table directly with raw UPDATEs, bypassing all repository code,
because the schema is the last line of defence.
"""

import sqlite3
from itertools import product
from pathlib import Path

import aiosqlite
import pytest

from engine.storage import apply_migrations, open_sqlite_connection

ALL_STATUSES = ("pending", "approved", "executing", "executed", "failed", "dismissed")
LEGAL_TRANSITIONS = frozenset(
    {
        ("pending", "approved"),
        ("pending", "dismissed"),
        ("approved", "executing"),
        ("executing", "executed"),
        ("executing", "failed"),
    }
)
# The legal single-step path INTO each state, used to set fixtures up
# through the schema itself (never by editing status directly).
_PATH_TO_STATUS: dict[str, tuple[tuple[str, str], ...]] = {
    "pending": (),
    "approved": (("pending", "approved"),),
    "dismissed": (("pending", "dismissed"),),
    "executing": (("pending", "approved"), ("approved", "executing")),
    "executed": (
        ("pending", "approved"),
        ("approved", "executing"),
        ("executing", "executed"),
    ),
    "failed": (
        ("pending", "approved"),
        ("approved", "executing"),
        ("executing", "failed"),
    ),
}
_TS = "2026-07-06T00:00:00+00:00"


async def _migrated_connection(
    tmp_db_path: Path, real_migrations_dir: Path
) -> aiosqlite.Connection:
    await apply_migrations(tmp_db_path, real_migrations_dir)
    return await open_sqlite_connection(tmp_db_path)


async def _insert_pending(conn: aiosqlite.Connection) -> int:
    cursor = await conn.execute(
        "INSERT INTO approval_cards"
        " (meeting_id, source, source_row_id, card_type, payload_json, status, created_at)"
        " VALUES (NULL, 'dictation', 1, 'write_note', '{}', 'pending', ?)",
        (_TS,),
    )
    assert cursor.lastrowid is not None
    return int(cursor.lastrowid)


async def _apply_transition(conn: aiosqlite.Connection, card_id: int, to_status: str) -> None:
    """One legal step, with the timestamps the triggers demand."""
    await conn.execute(
        "UPDATE approval_cards SET status = ?,"
        " decided_at = CASE WHEN ? IN ('approved','dismissed') THEN ? ELSE decided_at END,"
        " executed_at = CASE WHEN ? IN ('executed','failed') THEN ? ELSE executed_at END"
        " WHERE id = ?",
        (to_status, to_status, _TS, to_status, _TS, card_id),
    )


async def _card_in_status(conn: aiosqlite.Connection, status: str) -> int:
    card_id = await _insert_pending(conn)
    for _, to_status in _PATH_TO_STATUS[status]:
        await _apply_transition(conn, card_id, to_status)
    return card_id


async def _status_of(conn: aiosqlite.Connection, card_id: int) -> str:
    cursor = await conn.execute(
        "SELECT status FROM approval_cards WHERE id = ?", (card_id,)
    )
    row = await cursor.fetchone()
    await cursor.close()
    assert row is not None
    return str(row[0])


@pytest.mark.parametrize(
    ("from_status", "to_status"),
    [
        pair
        for pair in product(ALL_STATUSES, ALL_STATUSES)
        if pair not in LEGAL_TRANSITIONS
    ],
)
async def test_every_illegal_transition_aborts_at_the_sql_layer(
    tmp_db_path: Path, real_migrations_dir: Path, from_status: str, to_status: str
) -> None:
    """The full 36-pair matrix minus the 5 legal edges: all must abort —
    including same->same (terminal rows are immutable by construction)."""
    conn = await _migrated_connection(tmp_db_path, real_migrations_dir)
    try:
        card_id = await _card_in_status(conn, from_status)
        with pytest.raises(sqlite3.DatabaseError, match="approval_cards"):
            await _apply_transition(conn, card_id, to_status)
        # The attack changed NOTHING: the row still shows the from-status.
        assert await _status_of(conn, card_id) == from_status
    finally:
        await conn.close()


@pytest.mark.parametrize(("from_status", "to_status"), sorted(LEGAL_TRANSITIONS))
async def test_every_legal_transition_is_allowed(
    tmp_db_path: Path, real_migrations_dir: Path, from_status: str, to_status: str
) -> None:
    conn = await _migrated_connection(tmp_db_path, real_migrations_dir)
    try:
        card_id = await _card_in_status(conn, from_status)
        await _apply_transition(conn, card_id, to_status)
        assert await _status_of(conn, card_id) == to_status
    finally:
        await conn.close()


@pytest.mark.parametrize("status", [s for s in ALL_STATUSES if s != "pending"])
async def test_cards_cannot_be_born_in_any_non_pending_status(
    tmp_db_path: Path, real_migrations_dir: Path, status: str
) -> None:
    """Inserting a pre-approved/pre-executed card bypasses the user: abort."""
    conn = await _migrated_connection(tmp_db_path, real_migrations_dir)
    try:
        with pytest.raises(sqlite3.DatabaseError, match="pending"):
            await conn.execute(
                "INSERT INTO approval_cards"
                " (source, source_row_id, card_type, payload_json, status, created_at)"
                " VALUES ('extraction', 1, 'create_event', '{}', ?, ?)",
                (status, _TS),
            )
        cursor = await conn.execute("SELECT COUNT(*) FROM approval_cards")
        row = await cursor.fetchone()
        await cursor.close()
        assert row is not None and int(row[0]) == 0
    finally:
        await conn.close()


async def test_approving_without_decided_at_aborts(
    tmp_db_path: Path, real_migrations_dir: Path
) -> None:
    conn = await _migrated_connection(tmp_db_path, real_migrations_dir)
    try:
        card_id = await _insert_pending(conn)
        with pytest.raises(sqlite3.DatabaseError, match="decided_at"):
            await conn.execute(
                "UPDATE approval_cards SET status = 'approved' WHERE id = ?", (card_id,)
            )
    finally:
        await conn.close()


async def test_finishing_without_executed_at_aborts(
    tmp_db_path: Path, real_migrations_dir: Path
) -> None:
    conn = await _migrated_connection(tmp_db_path, real_migrations_dir)
    try:
        card_id = await _card_in_status(conn, "executing")
        with pytest.raises(sqlite3.DatabaseError, match="executed_at"):
            await conn.execute(
                "UPDATE approval_cards SET status = 'executed' WHERE id = ?", (card_id,)
            )
    finally:
        await conn.close()


@pytest.mark.parametrize(
    "attack_sql",
    [
        "UPDATE approval_cards SET source = 'dictation' WHERE id = ?",
        "UPDATE approval_cards SET source_row_id = 999 WHERE id = ?",
        "UPDATE approval_cards SET card_type = 'draft_email' WHERE id = ?",
        "UPDATE approval_cards SET created_at = '1999-01-01T00:00:00+00:00' WHERE id = ?",
        "UPDATE approval_cards SET meeting_id = 'm-forged' WHERE id = ?",
    ],
)
async def test_provenance_columns_are_immutable(
    tmp_db_path: Path, real_migrations_dir: Path, attack_sql: str
) -> None:
    """A card's lineage back to its source row can never be rewritten."""
    conn = await _migrated_connection(tmp_db_path, real_migrations_dir)
    try:
        cursor = await conn.execute(
            "INSERT INTO approval_cards"
            " (source, source_row_id, card_type, payload_json, status, created_at)"
            " VALUES ('extraction', 7, 'create_event', '{}', 'pending', ?)",
            (_TS,),
        )
        card_id = int(cursor.lastrowid or 0)
        with pytest.raises(sqlite3.DatabaseError):
            await conn.execute(attack_sql, (card_id,))
    finally:
        await conn.close()


async def test_payload_is_locked_after_the_decision_but_editable_while_pending(
    tmp_db_path: Path, real_migrations_dir: Path
) -> None:
    """What the user approved is what executes: pending->approved may carry
    the edit; approved->executing (or any later step) may NOT change it."""
    conn = await _migrated_connection(tmp_db_path, real_migrations_dir)
    try:
        card_id = await _insert_pending(conn)
        # Edit riding the approval statement: allowed.
        await conn.execute(
            "UPDATE approval_cards SET status = 'approved', decided_at = ?,"
            " payload_json = '{\"title\": \"edited\"}' WHERE id = ?",
            (_TS, card_id),
        )
        # Any later payload change: refused.
        with pytest.raises(sqlite3.DatabaseError, match="locked"):
            await conn.execute(
                "UPDATE approval_cards SET status = 'executing',"
                " payload_json = '{\"title\": \"tampered\"}' WHERE id = ?",
                (card_id,),
            )
        cursor = await conn.execute(
            "SELECT payload_json, status FROM approval_cards WHERE id = ?", (card_id,)
        )
        row = await cursor.fetchone()
        await cursor.close()
        assert row is not None
        assert row[0] == '{"title": "edited"}'
        assert row[1] == "approved"  # the tamper attempt changed nothing
    finally:
        await conn.close()


async def test_delete_is_forbidden(tmp_db_path: Path, real_migrations_dir: Path) -> None:
    conn = await _migrated_connection(tmp_db_path, real_migrations_dir)
    try:
        card_id = await _insert_pending(conn)
        with pytest.raises(sqlite3.DatabaseError, match="DELETE is forbidden"):
            await conn.execute("DELETE FROM approval_cards WHERE id = ?", (card_id,))
        assert await _status_of(conn, card_id) == "pending"
    finally:
        await conn.close()
