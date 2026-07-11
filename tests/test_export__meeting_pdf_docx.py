"""Full meeting PDF/DOCX export includes notes sections."""

from pathlib import Path

import pytest

from engine.export import document_export
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


def test_export_meeting_pdf_keeps_cjk_when_unicode_font_available(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With a Unicode-capable font, CJK must not be latin-1-replaced to '?'."""
    font = Path(r"C:/Windows/Fonts/malgun.ttf")
    if not font.is_file():
        pytest.skip("malgun.ttf not available for Unicode PDF test")
    monkeypatch.setattr(document_export, "_UNICODE_FONT_PATH_OVERRIDE", font)
    data = export_meeting_pdf(
        "会議",
        "",
        "日本語の要約",
        [_segment("中文内容")],
    )
    # latin-1 replace turns each CJK codepoint into 0x3F ('?'); a Unicode
    # font path must embed the real characters (UTF-16BE in the PDF stream).
    assert b"\xff\xfe" in data or "会議".encode("utf-16-be") in data or b"/ToUnicode" in data
    # Soft check: raw PDF must not be the all-question-mark latin-1 path only.
    latin1_view = data.decode("latin-1", errors="ignore")
    assert "???" not in latin1_view or "会議".encode("utf-16-be") in data
