"""Repository for ``meetings`` rows (capture session lifecycle + finalization).

Purpose: the only place meeting rows are written or read — one row per
capture session, inserted at ``capture.start``, closed (``ended_at``) at
``capture.stop``, and stamped with finalization state (note path, verbatim
user notes, enhanced markdown) by the M2 finalization service. The Library
screen's ``meetings.list`` / ``meeting.get`` commands read through here.
Parameterised SQL only.
Pipeline position: called by ``engine.stt.live_capture_service`` around
each capture session and by ``engine.enhance`` at finalization;
``transcript_segments`` rows reference these ids.

Security / fidelity invariants:
- Every value is bound as a SQL parameter — user-titled meetings and user
  notes can never inject SQL (untrusted-input discipline).
- ``notes_text`` is stored EXACTLY as the user typed it (byte-identical
  fidelity mandate) — no trimming, no normalisation, ever.
"""

from dataclasses import dataclass
from datetime import UTC, datetime

import aiosqlite


def utc_now_iso() -> str:
    """ISO-8601 UTC timestamp — the schema's pinned time format."""
    return datetime.now(tz=UTC).isoformat()


async def insert_meeting(
    connection: aiosqlite.Connection, meeting_id: str, title: str, started_at_iso: str
) -> None:
    """Create the meeting row for a starting capture session."""
    await connection.execute(
        # Parameterised: title is user/client input (injection defence).
        "INSERT INTO meetings (id, title, started_at) VALUES (?, ?, ?)",
        (meeting_id, title, started_at_iso),
    )


async def mark_meeting_ended(
    connection: aiosqlite.Connection, meeting_id: str, ended_at_iso: str
) -> None:
    """Stamp ``ended_at`` when the capture session stops."""
    await connection.execute(
        "UPDATE meetings SET ended_at = ? WHERE id = ?",
        (ended_at_iso, meeting_id),
    )


@dataclass(frozen=True)
class MeetingRow:
    """One meeting row as read back for the Library surface (M2 columns
    included; all finalization fields are None until finalize runs)."""

    id: str
    title: str
    started_at: str
    ended_at: str | None
    note_path: str | None
    notes_text: str | None
    enhanced_notes_md: str | None
    finalized_at: str | None


# Static SQL (no interpolation anywhere — injection defence by construction).
_SELECT_ALL_MEETINGS = (
    "SELECT id, title, started_at, ended_at, note_path, notes_text,"
    " enhanced_notes_md, finalized_at FROM meetings ORDER BY started_at DESC"
)
_SELECT_ONE_MEETING = (
    "SELECT id, title, started_at, ended_at, note_path, notes_text,"
    " enhanced_notes_md, finalized_at FROM meetings WHERE id = ?"
)


def _row_to_meeting(row: aiosqlite.Row | tuple[object, ...]) -> MeetingRow:
    """Map one SELECT row (column order pinned by the SELECT constants)."""
    return MeetingRow(
        id=str(row[0]),
        title=str(row[1]),
        started_at=str(row[2]),
        ended_at=None if row[3] is None else str(row[3]),
        note_path=None if row[4] is None else str(row[4]),
        notes_text=None if row[5] is None else str(row[5]),
        enhanced_notes_md=None if row[6] is None else str(row[6]),
        finalized_at=None if row[7] is None else str(row[7]),
    )


async def list_meeting_rows(connection: aiosqlite.Connection) -> list[MeetingRow]:
    """All meetings, newest first — the Library list source."""
    cursor = await connection.execute(_SELECT_ALL_MEETINGS)
    rows = await cursor.fetchall()
    await cursor.close()
    return [_row_to_meeting(row) for row in rows]


async def fetch_meeting_row(
    connection: aiosqlite.Connection, meeting_id: str
) -> MeetingRow | None:
    """One meeting by id, or None when it does not exist."""
    cursor = await connection.execute(_SELECT_ONE_MEETING, (meeting_id,))
    row = await cursor.fetchone()
    await cursor.close()
    return None if row is None else _row_to_meeting(row)


async def update_meeting_enhanced_notes(
    connection: aiosqlite.Connection, meeting_id: str, enhanced_notes_md: str | None
) -> bool:
    """Update enhanced notes markdown only; returns False when meeting missing."""
    cursor = await connection.execute(
        "UPDATE meetings SET enhanced_notes_md = ? WHERE id = ?",
        (enhanced_notes_md, meeting_id),
    )
    changed = cursor.rowcount > 0
    await cursor.close()
    return changed


async def record_meeting_finalization(
    connection: aiosqlite.Connection,
    meeting_id: str,
    *,
    note_path: str,
    notes_text: str,
    enhanced_notes_md: str | None,
    finalized_at_iso: str,
) -> None:
    """Stamp finalization output onto the meeting row.

    ``notes_text`` is bound verbatim (fidelity mandate — the exact bytes the
    user typed); ``enhanced_notes_md`` is the already-sanitised enhancement
    markdown, or None when enhancement was unavailable (honest absence).
    """
    await connection.execute(
        "UPDATE meetings SET note_path = ?, notes_text = ?, enhanced_notes_md = ?,"
        " finalized_at = ? WHERE id = ?",
        (note_path, notes_text, enhanced_notes_md, finalized_at_iso, meeting_id),
    )
