"""Presenter layer: exact duration arithmetic + summary derivation, pinned keys.

Deterministic paths must be exact to the unit (zero-numerical-error rule):
half-up minute rounding is tested on / just-over / just-under every rounding
boundary, and the summary's 160-character cap is tested at 159/160/161. The
payload key sets are pinned — the TypeScript repository mirrors them, so a
renamed key here is a broken Library screen.
"""

import pytest

from engine.enhance.meeting_summary_presenter import (
    derive_one_line_summary,
    duration_minutes,
    meeting_detail_payload,
    meeting_summary_payload,
)
from engine.storage.meetings_repository import MeetingRow
from engine.storage.transcript_segments_repository import TranscriptSegmentRow

START = "2026-07-06T10:00:00+00:00"


def _ended(seconds: int) -> str:
    minutes, secs = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    return f"2026-07-06T{10 + hours:02d}:{minutes:02d}:{secs:02d}+00:00"


# ----------------------------------------------------------- duration exact
@pytest.mark.parametrize(
    ("seconds", "expected"),
    [
        (0, 1),  # instant stop: a meeting that happened is never "0 min"
        (1, 1),
        (29, 1),  # just under the first half-up boundary
        (30, 1),  # ON the boundary: (30+30)//60 == 1
        (31, 1),
        (89, 1),  # just under
        (90, 2),  # ON: rounds up
        (91, 2),
        (149, 2),
        (150, 3),
        (3599, 60),
        (3600, 60),
        (3630, 61),  # half-up across the hour
    ],
)
def test_duration_half_up_rounding_is_exact_at_every_boundary(
    seconds: int, expected: int
) -> None:
    assert duration_minutes(START, _ended(seconds)) == expected


def test_duration_is_zero_while_open_and_on_bad_or_negative_input() -> None:
    assert duration_minutes(START, None) == 0
    assert duration_minutes(START, "not-a-timestamp") == 0
    assert duration_minutes("garbage", _ended(60)) == 0
    assert duration_minutes(_ended(600), START) == 0  # ended before it started


# ------------------------------------------------------------ summary lines
def test_summary_takes_the_first_substantive_line_and_strips_markup() -> None:
    markdown = (
        "# Heading skipped\n\n---\n\n- [ ] **Renewal** agreed at `$40k`, _pending_ SSO.\n"
        "second line never chosen"
    )
    assert (
        derive_one_line_summary(markdown) == "Renewal agreed at $40k, pending SSO."
    )


@pytest.mark.parametrize("empty_input", [None, "", "# only\n## headings\n---\n***\n"])
def test_summary_is_empty_when_nothing_substantive_exists(empty_input: str | None) -> None:
    assert derive_one_line_summary(empty_input) == ""


def test_summary_cap_boundary_exact_at_159_160_161() -> None:
    assert derive_one_line_summary("x" * 159) == "x" * 159  # under: untouched
    assert derive_one_line_summary("x" * 160) == "x" * 160  # on: untouched
    over = derive_one_line_summary("x" * 161)  # one over: cut + ellipsis
    assert over == "x" * 159 + "…"
    assert len(over) == 160


def test_summary_never_invents_text() -> None:
    """Whatever comes back is a verbatim (markup-stripped) substring of the
    enhancement output — the 'why matches the what' contract."""
    markdown = "## S\nThe team agreed to ship on *Friday*.\n"
    summary = derive_one_line_summary(markdown)
    assert summary == "The team agreed to ship on Friday."
    assert summary.replace(" ", "") in markdown.replace("*", "").replace(" ", "")


# -------------------------------------------------------------- pinned keys
ROW = MeetingRow(
    id="m-1",
    title="Vendor sync",
    started_at=START,
    ended_at=_ended(90),
    note_path="Meetings/2026-07-06 Vendor sync.md",
    notes_text="raw notes",
    enhanced_notes_md="## Summary\nAll agreed.\n",
    finalized_at="2026-07-06T11:00:00+00:00",
)


def test_summary_payload_keys_and_values_are_pinned_for_the_ts_mirror() -> None:
    payload = meeting_summary_payload(ROW)
    assert payload == {
        "id": "m-1",
        "title": "Vendor sync",
        "summary": "All agreed.",
        "start_iso": START,
        "duration_min": 2,
    }


def test_detail_payload_keys_and_values_are_pinned_for_the_ts_mirror() -> None:
    segments = [
        TranscriptSegmentRow(
            segment_id="s1", stream="them", speaker_id="1", text="hello", t_start=0.0, t_end=1.0
        ),
        TranscriptSegmentRow(
            segment_id="s2", stream="me", speaker_id="me", text="hi", t_start=1.2, t_end=1.8
        ),
    ]
    payload = meeting_detail_payload(ROW, segments)
    assert payload == {
        "id": "m-1",
        "title": "Vendor sync",
        "start_iso": START,
        "ended_iso": _ended(90),
        "duration_min": 2,
        "finalized": True,
        "note_path": "Meetings/2026-07-06 Vendor sync.md",
        "notes_text": "raw notes",
        "enhanced_notes_md": "## Summary\nAll agreed.\n",
        "extraction": None,
        "has_kept_audio": False,
        "transcript": [
            {
                "segment_id": "s1",
                "stream": "them",
                "speaker_id": "1",
                "speaker_label": "Speaker 1",
                "text": "hello",
                "t_start": 0.0,
                "t_end": 1.0,
            },
            {
                "segment_id": "s2",
                "stream": "me",
                "speaker_id": "me",
                "speaker_label": "Me",
                "text": "hi",
                "t_start": 1.2,
                "t_end": 1.8,
            },
        ],
    }


def test_detail_payload_degrades_honestly_for_an_unfinalized_meeting() -> None:
    open_row = MeetingRow(
        id="m-2",
        title="Live now",
        started_at=START,
        ended_at=None,
        note_path=None,
        notes_text=None,
        enhanced_notes_md=None,
        finalized_at=None,
    )
    payload = meeting_detail_payload(open_row, [])
    assert payload["finalized"] is False
    assert payload["duration_min"] == 0
    assert payload["notes_text"] == "" and payload["enhanced_notes_md"] == ""
    assert payload["transcript"] == []
