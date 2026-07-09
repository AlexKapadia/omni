"""Tests for meeting markdown export."""

from engine.export.transcript_export import export_meeting_markdown
from engine.storage.transcript_segments_repository import TranscriptSegmentRow


def test_export_meeting_markdown_includes_sections() -> None:
    segments = [
        TranscriptSegmentRow("s1", "them", "1", "Hello", 0.0, 1.0),
        TranscriptSegmentRow("s2", "me", "me", "Hi", 1.0, 2.0),
    ]
    md = export_meeting_markdown(
        "Standup",
        "rough notes",
        "## Summary\nDone.",
        segments,
        "Alex",
    )
    assert "# Standup" in md
    assert "## Enhanced Notes" in md
    assert "## My Notes" in md
    assert "rough notes" in md
    assert "**Speaker 1:** Hello" in md
    assert "**Alex:** Hi" in md
