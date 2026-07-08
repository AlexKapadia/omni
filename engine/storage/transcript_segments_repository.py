"""Repository for ``transcript_segments`` rows (final transcript persistence).

Purpose: the only writer of transcript segments — every
``transcript.final`` event lands here as one row, verbatim.
Pipeline position: called by ``engine.stt.live_capture_service`` when a
speech segment finalises; M3's indexer reads these rows later.

Security / fidelity invariants:
- Parameterised SQL only — transcript text is untrusted content and must
  never be interpolated (injection defence).
- The ``text`` value is stored EXACTLY as merged from the model output —
  the raw transcript is ground truth (fidelity mandate); the DB schema's
  CHECK constraint enforces the pinned stream labels.
"""

from dataclasses import dataclass

import aiosqlite


@dataclass(frozen=True)
class TranscriptSegmentRow:
    """One finalised segment as read back for finalization / the detail view."""

    segment_id: str
    stream: str  # 'me' | 'them' (DB CHECK constraint)
    text: str  # verbatim model text (fidelity mandate)
    t_start: float
    t_end: float


async def list_transcript_segment_rows(
    connection: aiosqlite.Connection, meeting_id: str
) -> list[TranscriptSegmentRow]:
    """All segments of one meeting in spoken order (t_start, then id).

    Read-only companion to the writer above — the M2 finalizer and the
    ``meeting.get`` command build the transcript view from these rows.
    """
    cursor = await connection.execute(
        "SELECT id, stream, text, t_start, t_end FROM transcript_segments"
        " WHERE meeting_id = ? ORDER BY t_start, id",
        (meeting_id,),
    )
    rows = await cursor.fetchall()
    await cursor.close()
    return [
        TranscriptSegmentRow(
            segment_id=str(row[0]),
            stream=str(row[1]),
            text=str(row[2]),
            t_start=float(row[3]),
            t_end=float(row[4]),
        )
        for row in rows
    ]


async def insert_transcript_segment(
    connection: aiosqlite.Connection,
    segment_id: str,
    meeting_id: str,
    stream: str,
    text: str,
    t_start: float,
    t_end: float,
    created_at_iso: str,
) -> None:
    """Persist one finalised segment (verbatim text, meeting-relative times)."""
    await connection.execute(
        # Parameterised: text/stream come from the pipeline but are treated
        # as untrusted at the storage boundary regardless (deny by default).
        "INSERT INTO transcript_segments"
        " (id, meeting_id, stream, text, t_start, t_end, created_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?)",
        (segment_id, meeting_id, stream, text, t_start, t_end, created_at_iso),
    )


async def update_transcript_segment_text(
    connection: aiosqlite.Connection,
    meeting_id: str,
    segment_id: str,
    text: str,
) -> bool:
    """Update one segment's text; returns False when no row matched."""
    cursor = await connection.execute(
        "UPDATE transcript_segments SET text = ? WHERE meeting_id = ? AND id = ?",
        (text, meeting_id, segment_id),
    )
    changed = cursor.rowcount > 0
    await cursor.close()
    return changed
