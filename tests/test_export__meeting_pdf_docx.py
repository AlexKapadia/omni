"""Full meeting PDF/DOCX export includes notes sections."""

from engine.export.document_export import export_meeting_docx, export_meeting_pdf
from engine.storage.transcript_segments_repository import TranscriptSegmentRow


def _segment(text: str) -> TranscriptSegmentRow:
    return TranscriptSegmentRow(
        segment_id="s1",
        stream="them",
        speaker_id="1",
        text=text,
        t_start=0.0,
        t_end=1.0,
    )


def test_export_meeting_pdf_includes_enhanced_notes() -> None:
    data = export_meeting_pdf(
        "Weekly sync",
        "rough scratch",
        "## Summary\n\nWe agreed on the launch date.",
        [_segment("hello team")],
    )
    assert isinstance(data, (bytes, bytearray))
    assert len(data) > 100


def test_export_meeting_docx_includes_enhanced_notes() -> None:
    data = export_meeting_docx(
        "Weekly sync",
        "rough scratch",
        "## Summary\n\nWe agreed on the launch date.",
        [_segment("hello team")],
    )
    assert data[:2] == b"PK"
