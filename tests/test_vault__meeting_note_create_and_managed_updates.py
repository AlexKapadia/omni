"""Meeting note writer: creation shape, managed updates, user-text preservation.

Covers: full note structure (frontmatter, My Notes, managed Enhanced Notes /
Actions / Transcript in a collapsed callout), unicode titles/attendees,
collision suffixing, replace-managed-region-only updates that leave the
user's ``## My Notes`` edits byte-identical, and write idempotency.
"""

from pathlib import Path

from engine.vault.frontmatter_codec import parse_frontmatter
from engine.vault.managed_region_rewriter import (
    REGION_ACTIONS,
    REGION_ENHANCED_NOTES,
    REGION_TRANSCRIPT,
    close_marker,
    open_marker,
)
from engine.vault.meeting_note_writer import (
    create_meeting_note,
    format_transcript_callout,
    update_meeting_actions,
    update_meeting_enhanced_notes,
    update_meeting_transcript,
)

_ATTENDEES = ["Alice O'Hara", "评审主持人", "🚀 Bob", "مرحبا", "שלום"]


def _create(tmp_path: Path, title: str = "Weekly Sync: Q3 🚀") -> Path:
    return create_meeting_note(
        tmp_path,
        title=title,
        date_iso="2026-07-06",
        attendees=_ATTENDEES,
        tags=["meeting", "q3"],
        calendar_event_id="evt_42",
        disclosed=True,
        my_notes="my rough note",
        transcript_lines=["hello there", "", "第二行 second line"],
    )


def test_created_note_lands_in_meetings_with_sanitized_dated_name(tmp_path: Path) -> None:
    path = _create(tmp_path)
    assert path.parent == tmp_path / "Meetings"
    assert path.name == "2026-07-06 Weekly Sync Q3 🚀.md"  # ':' sanitized away
    assert path.exists()


def test_frontmatter_round_trips_all_meeting_fields(tmp_path: Path) -> None:
    text = _create(tmp_path).read_text(encoding="utf-8")
    fields, _ = parse_frontmatter(text)
    assert fields == {
        "date": "2026-07-06",
        "title": "Weekly Sync: Q3 🚀",
        "attendees": _ATTENDEES,
        "tags": ["meeting", "q3"],
        "calendar_event_id": "evt_42",
        "disclosed": True,
    }


def test_omitted_calendar_event_id_is_absent_not_null(tmp_path: Path) -> None:
    path = create_meeting_note(tmp_path, title="No Calendar", date_iso="2026-07-06")
    assert "calendar_event_id" not in path.read_text(encoding="utf-8")


def test_note_sections_appear_in_contract_order_with_all_markers(tmp_path: Path) -> None:
    text = _create(tmp_path).read_text(encoding="utf-8")
    order = [
        "## My Notes",
        "## Enhanced Notes",
        open_marker(REGION_ENHANCED_NOTES),
        close_marker(REGION_ENHANCED_NOTES),
        "## Actions",
        open_marker(REGION_ACTIONS),
        close_marker(REGION_ACTIONS),
        "## Transcript",
        open_marker(REGION_TRANSCRIPT),
        "> [!note]- Transcript",
        close_marker(REGION_TRANSCRIPT),
    ]
    positions = [text.index(piece) for piece in order]
    assert positions == sorted(positions)
    assert "my rough note" in text


def test_transcript_lines_are_quoted_inside_the_collapsed_callout(tmp_path: Path) -> None:
    text = _create(tmp_path).read_text(encoding="utf-8")
    assert "> hello there" in text
    assert "> 第二行 second line" in text
    # The empty transcript line stays inside the quote (bare '>').
    assert "\n>\n" in text


def test_transcript_callout_contains_multiline_segments() -> None:
    """Embedded newlines cannot escape the callout quoting (containment)."""
    rendered = format_transcript_callout(["one\ntwo", "three"])
    for line in rendered.split("\n"):
        assert line.startswith(">")


def test_empty_transcript_renders_honest_placeholder() -> None:
    assert "_No transcript captured._" in format_transcript_callout([])


def test_same_title_twice_collision_suffixes_never_overwrites(tmp_path: Path) -> None:
    first = _create(tmp_path)
    second = _create(tmp_path)
    assert first != second
    assert second.name.endswith(" (2).md")
    assert first.exists() and second.exists()


def test_managed_updates_preserve_user_edits_everywhere_else(tmp_path: Path) -> None:
    """The core invariant end-to-end: user edits survive every update op."""
    path = _create(tmp_path)
    # Simulate the user editing My Notes (and adding CRLF lines) in Obsidian.
    original = path.read_bytes()
    edited = original.replace(
        b"my rough note", "my EDITED note \r\nwith a CRLF line 🚀".encode()
    )
    path.write_bytes(edited)

    update_meeting_enhanced_notes(path, "## Summary\n- point one\n- point two")
    update_meeting_actions(path, "- [ ] send deck to Alice")
    update_meeting_transcript(path, ["revised line"])

    final = path.read_bytes()
    assert "my EDITED note \r\nwith a CRLF line 🚀".encode() in final
    assert b"## Summary" in final
    assert b"- [ ] send deck to Alice" in final
    assert b"> revised line" in final
    assert b"hello there" not in final  # transcript was replaced, not appended
    # Frontmatter untouched by managed updates.
    fields, _ = parse_frontmatter(final.decode("utf-8"))
    assert fields["title"] == "Weekly Sync: Q3 🚀"


def test_update_with_identical_content_is_byte_identical_idempotent(tmp_path: Path) -> None:
    path = _create(tmp_path)
    update_meeting_enhanced_notes(path, "stable summary")
    once = path.read_bytes()
    update_meeting_enhanced_notes(path, "stable summary")
    assert path.read_bytes() == once


def test_updates_leave_no_temp_file_litter(tmp_path: Path) -> None:
    path = _create(tmp_path)
    update_meeting_actions(path, "- [ ] item")
    leftovers = [p.name for p in (tmp_path / "Meetings").iterdir() if p != path]
    assert leftovers == []
