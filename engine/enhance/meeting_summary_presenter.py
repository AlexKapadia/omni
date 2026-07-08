"""Presentation shaping for meetings.list / meeting.get reply payloads.

Purpose: pure, deterministic functions that turn storage rows into the
exact wire payloads the Library UI renders — one-line summaries derived
from enhanced markdown, exact duration arithmetic, and the pinned payload
field names (the TypeScript repository mirrors these keys).
Pipeline position: between ``engine.storage``'s row types and
``meeting_command_dispatcher``'s replies. No I/O here — everything is
unit-testable to the character.

Correctness invariants:
- Duration arithmetic is exact and pinned: half-up rounding to whole
  minutes, minimum 1 for any ended meeting (a meeting that happened is
  never shown as "0 min"); unparseable timestamps degrade to 0, honestly.
- Summary derivation never invents text: it is always a verbatim line of
  the enhancement output (markup stripped), or empty.
"""

import re
from datetime import datetime

import json

from engine.storage.meetings_repository import MeetingRow
from engine.storage.transcript_segments_repository import TranscriptSegmentRow

# Library rows show a one-liner; beyond this we cut on the cap, with ellipsis.
_SUMMARY_MAX_CHARS = 160

# Leading markdown noise a summary line sheds: bullets, checkboxes, emphasis.
_LEADING_MARKUP = re.compile(r"^(?:[-*+]\s+|\[.?\]\s+|>\s+)+")
_EMPHASIS_MARKS = re.compile(r"[*_`]")


def derive_one_line_summary(enhanced_markdown: str | None) -> str:
    """First substantive line of the enhanced notes, as plain text.

    Skips headings, horizontal rules, and blank lines; strips list/emphasis
    markup from the chosen line. Returns "" when there is nothing usable —
    the UI treats an empty summary as "not enhanced yet".
    """
    if not enhanced_markdown:
        return ""
    for raw_line in enhanced_markdown.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or set(line) <= {"-", "=", "*", "_"}:
            continue
        line = _LEADING_MARKUP.sub("", line)
        line = _EMPHASIS_MARKS.sub("", line).strip()
        if not line:
            continue
        if len(line) > _SUMMARY_MAX_CHARS:
            return line[: _SUMMARY_MAX_CHARS - 1].rstrip() + "…"
        return line
    return ""


def duration_minutes(started_at_iso: str, ended_at_iso: str | None) -> int:
    """Whole-minute duration, half-up, minimum 1 once ended; 0 while open.

    Pinned arithmetic (zero-numerical-error rule): ``(seconds + 30) // 60``
    is exact integer half-up — 29 s -> 1 (floor 0, minimum applies),
    30 s -> 1, 89 s -> 1, 90 s -> 2. Unparseable/negative inputs -> 0.
    """
    if ended_at_iso is None:
        return 0
    try:
        started = datetime.fromisoformat(started_at_iso)
        ended = datetime.fromisoformat(ended_at_iso)
    except ValueError:
        return 0  # honest degradation: never crash the list on one bad row
    seconds = int((ended - started).total_seconds())
    if seconds < 0:
        return 0
    return max(1, int((seconds + 30) // 60))


def meeting_summary_payload(row: MeetingRow) -> dict[str, object]:
    """One ``meetings.list`` row — field names pinned by the TS mirror."""
    return {
        "id": row.id,
        "title": row.title,
        "summary": derive_one_line_summary(row.enhanced_notes_md),
        "start_iso": row.started_at,
        "duration_min": duration_minutes(row.started_at, row.ended_at),
    }


def meeting_detail_payload(
    row: MeetingRow,
    segments: list[TranscriptSegmentRow],
    extraction_json: str | None = None,
) -> dict[str, object]:
    """The ``meeting.get`` payload — field names pinned by the TS mirror.

    ``notes_text`` is the user's verbatim notes (fidelity mandate);
    ``transcript`` is the persisted verbatim segments in spoken order.
    """
    extraction: object | None = None
    if extraction_json:
        try:
            extraction = json.loads(extraction_json)
        except json.JSONDecodeError:
            extraction = None
    return {
        "id": row.id,
        "title": row.title,
        "start_iso": row.started_at,
        "ended_iso": row.ended_at,
        "duration_min": duration_minutes(row.started_at, row.ended_at),
        "finalized": row.finalized_at is not None,
        "note_path": row.note_path,
        "notes_text": row.notes_text or "",
        "enhanced_notes_md": row.enhanced_notes_md or "",
        "extraction": extraction,
        "transcript": [
            {
                "segment_id": s.segment_id,
                "stream": s.stream,
                "text": s.text,
                "t_start": s.t_start,
                "t_end": s.t_end,
            }
            for s in segments
        ],
    }
