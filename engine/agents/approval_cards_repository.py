"""Repository over ``approval_cards`` (0008) — the only SQL touch-point.

Purpose: every read and every legal status transition of an approval card
goes through these functions. The transitions themselves are ENFORCED by the
0008 schema triggers; this module's job is parameterised SQL, honest
row-count checking, and the transactional executor claim.
Pipeline position: written by ``approval_card_builder`` (inserts) and the
(deferred) server wiring (approve/dismiss); ``card_executor`` claims and
finishes cards here.

Security invariants:
- Parameterised SQL only — payloads derive from untrusted model output.
- TOCTOU defence: :func:`claim_card_for_execution` re-checks the row's
  status INSIDE an immediate transaction, so two executors racing one card
  resolve to exactly one winner (the loser's UPDATE matches zero rows).
- Approve/dismiss are conditional UPDATEs (``WHERE status='pending'``) that
  report whether they actually happened — callers must not assume.
"""

import aiosqlite

from engine.agents.approval_card_types import ApprovalCardRecord

_COLUMNS = (
    "id, meeting_id, source, source_row_id, card_type, payload_json, status,"
    " created_at, decided_at, executed_at, result_json, error"
)


def _record_from_row(row: aiosqlite.Row | tuple[object, ...]) -> ApprovalCardRecord:
    return ApprovalCardRecord(
        id=int(row[0]),  # type: ignore[arg-type]
        meeting_id=None if row[1] is None else str(row[1]),
        source=str(row[2]),
        source_row_id=int(row[3]),  # type: ignore[arg-type]
        card_type=str(row[4]),
        payload_json=str(row[5]),
        status=str(row[6]),
        created_at=str(row[7]),
        decided_at=None if row[8] is None else str(row[8]),
        executed_at=None if row[9] is None else str(row[9]),
        result_json=None if row[10] is None else str(row[10]),
        error=None if row[11] is None else str(row[11]),
    )


async def insert_pending_card(
    connection: aiosqlite.Connection,
    *,
    meeting_id: str | None,
    source: str,
    source_row_id: int,
    card_type: str,
    payload_json: str,
    created_at: str,
) -> int:
    """Insert one card (born 'pending' — the 0008 trigger enforces it)."""
    cursor = await connection.execute(
        "INSERT INTO approval_cards"
        " (meeting_id, source, source_row_id, card_type, payload_json, status, created_at)"
        " VALUES (?, ?, ?, ?, ?, 'pending', ?)",
        (meeting_id, source, source_row_id, card_type, payload_json, created_at),
    )
    row_id = cursor.lastrowid
    await cursor.close()
    return int(row_id if row_id is not None else 0)


async def get_card(connection: aiosqlite.Connection, card_id: int) -> ApprovalCardRecord | None:
    """One card by id, or None."""
    cursor = await connection.execute(
        f"SELECT {_COLUMNS} FROM approval_cards WHERE id = ?",  # noqa: S608 — constant columns
        (card_id,),
    )
    row = await cursor.fetchone()
    await cursor.close()
    return None if row is None else _record_from_row(row)


async def list_cards(
    connection: aiosqlite.Connection, *, limit: int = 200
) -> list[ApprovalCardRecord]:
    """Newest-first cards (the UI rack's read path)."""
    cursor = await connection.execute(
        f"SELECT {_COLUMNS} FROM approval_cards ORDER BY id DESC LIMIT ?",  # noqa: S608 — constant columns
        (limit,),
    )
    rows = await cursor.fetchall()
    await cursor.close()
    return [_record_from_row(row) for row in rows]


async def identical_card_exists(
    connection: aiosqlite.Connection,
    *,
    source: str,
    source_row_id: int,
    card_type: str,
    payload_json: str,
) -> bool:
    """Idempotent-builder check: has this exact suggestion been made already?"""
    cursor = await connection.execute(
        "SELECT 1 FROM approval_cards WHERE source = ? AND source_row_id = ?"
        " AND card_type = ? AND payload_json = ? LIMIT 1",
        (source, source_row_id, card_type, payload_json),
    )
    row = await cursor.fetchone()
    await cursor.close()
    return row is not None


async def approve_card(
    connection: aiosqlite.Connection,
    card_id: int,
    *,
    decided_at: str,
    edited_payload_json: str | None = None,
) -> bool:
    """pending -> approved (optionally carrying the user's pre-approval edit).

    Returns False when the card was not pending (already decided, racing, or
    missing) — the caller surfaces that honestly instead of assuming success.
    The edited payload rides the SAME statement because 0008 locks
    ``payload_json`` after the decision (what-you-approved-is-what-executes).
    """
    cursor = await connection.execute(
        "UPDATE approval_cards SET status = 'approved', decided_at = ?,"
        " payload_json = COALESCE(?, payload_json)"
        " WHERE id = ? AND status = 'pending'",
        (decided_at, edited_payload_json, card_id),
    )
    changed = cursor.rowcount == 1
    await cursor.close()
    return changed


async def dismiss_card(
    connection: aiosqlite.Connection, card_id: int, *, decided_at: str
) -> bool:
    """pending -> dismissed. Returns False when the card was not pending."""
    cursor = await connection.execute(
        "UPDATE approval_cards SET status = 'dismissed', decided_at = ?"
        " WHERE id = ? AND status = 'pending'",
        (decided_at, card_id),
    )
    changed = cursor.rowcount == 1
    await cursor.close()
    return changed


async def claim_card_for_execution(
    connection: aiosqlite.Connection, card_id: int
) -> ApprovalCardRecord | None:
    """approved -> executing, exactly once (the TOCTOU defence).

    BEGIN IMMEDIATE takes the write lock up front, then the conditional
    UPDATE re-checks ``status='approved'`` at the row level — a card another
    executor already claimed (or that was never approved) matches zero rows
    and this claim returns None. The winner gets the row AS CLAIMED, read
    inside the same transaction.
    """
    await connection.execute("BEGIN IMMEDIATE")
    try:
        cursor = await connection.execute(
            "UPDATE approval_cards SET status = 'executing'"
            " WHERE id = ? AND status = 'approved'",
            (card_id,),
        )
        claimed = cursor.rowcount == 1
        await cursor.close()
        if not claimed:
            await connection.execute("ROLLBACK")
            return None
        record_cursor = await connection.execute(
            f"SELECT {_COLUMNS} FROM approval_cards WHERE id = ?",  # noqa: S608 — constant columns
            (card_id,),
        )
        row = await record_cursor.fetchone()
        await record_cursor.close()
        await connection.execute("COMMIT")
        return None if row is None else _record_from_row(row)
    except BaseException:
        await connection.execute("ROLLBACK")
        raise


async def finish_card_executed(
    connection: aiosqlite.Connection,
    card_id: int,
    *,
    executed_at: str,
    result_json: str,
) -> bool:
    """executing -> executed, recording the tool's result."""
    cursor = await connection.execute(
        "UPDATE approval_cards SET status = 'executed', executed_at = ?, result_json = ?"
        " WHERE id = ? AND status = 'executing'",
        (executed_at, result_json, card_id),
    )
    changed = cursor.rowcount == 1
    await cursor.close()
    return changed


async def finish_card_failed(
    connection: aiosqlite.Connection,
    card_id: int,
    *,
    executed_at: str,
    error: str,
) -> bool:
    """executing -> failed, recording the plain-voice reason."""
    cursor = await connection.execute(
        "UPDATE approval_cards SET status = 'failed', executed_at = ?, error = ?"
        " WHERE id = ? AND status = 'executing'",
        (executed_at, error, card_id),
    )
    changed = cursor.rowcount == 1
    await cursor.close()
    return changed
