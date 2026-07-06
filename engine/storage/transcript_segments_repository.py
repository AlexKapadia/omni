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

import aiosqlite


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
