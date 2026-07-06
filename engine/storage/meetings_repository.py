"""Repository for ``meetings`` rows (capture session lifecycle).

Purpose: the only place meeting rows are written — one row per capture
session, inserted at ``capture.start`` and closed (``ended_at``) at
``capture.stop``. Parameterised SQL only.
Pipeline position: called by ``engine.stt.live_capture_service`` around
each capture session; ``transcript_segments`` rows reference these ids.

Security invariant: every value is bound as a SQL parameter — user-titled
meetings can never inject SQL (untrusted-input discipline).
"""

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
