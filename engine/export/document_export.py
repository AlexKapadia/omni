"""PDF and DOCX transcript export."""

from __future__ import annotations

import io
import re
from typing import Literal

from engine.storage.transcript_segments_repository import TranscriptSegmentRow
from engine.stt.speaker_voice_profile import resolve_speaker_label

ExportBinaryFormat = Literal["pdf", "docx"]


def _pdf_safe(text: str) -> str:
    return text.encode("latin-1", "replace").decode("latin-1")


def _pdf_write_lines(pdf: object, lines: list[str], *, line_height: float = 6) -> None:
    for line in lines:
        if line:
            pdf.multi_cell(pdf.epw, line_height, _pdf_safe(line))  # type: ignore[attr-defined]
        else:
            pdf.ln(3)  # type: ignore[attr-defined]


def _plain_lines_from_markdown(markdown: str) -> list[str]:
    lines: list[str] = []
    for raw in markdown.splitlines():
        line = raw.strip()
        if not line:
            lines.append("")
            continue
        if line.startswith("#"):
            lines.append(re.sub(r"^#+\s*", "", line))
            continue
        lines.append(line)
    return lines


def export_transcript_pdf(segments: list[TranscriptSegmentRow], identity: str = "Me") -> bytes:
    from fpdf import FPDF

    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.set_margins(15, 15, 15)
    pdf.add_page()
    pdf.set_font("Helvetica", size=11)
    for segment in segments:
        speaker = resolve_speaker_label(segment.speaker_id, identity)
        line = f"{speaker}: {segment.text}"
        pdf.multi_cell(0, 6, line)
        pdf.ln(2)
    return pdf.output()


def export_transcript_docx(segments: list[TranscriptSegmentRow], identity: str = "Me") -> bytes:
    from docx import Document

    document = Document()
    document.add_heading("Meeting transcript", level=1)
    for segment in segments:
        speaker = resolve_speaker_label(segment.speaker_id, identity)
        document.add_paragraph(f"{speaker}: {segment.text}")
    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()


def export_meeting_pdf(
    title: str,
    notes_text: str,
    enhanced_notes_md: str,
    segments: list[TranscriptSegmentRow],
    identity: str = "Me",
) -> bytes:
    from fpdf import FPDF

    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.set_margins(15, 15, 15)
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 16)
    pdf.multi_cell(pdf.epw, 8, _pdf_safe(title))
    pdf.ln(4)
    pdf.set_font("Helvetica", size=11)
    if enhanced_notes_md.strip():
        pdf.set_font("Helvetica", "B", 13)
        pdf.multi_cell(pdf.epw, 7, "Enhanced Notes")
        pdf.set_font("Helvetica", size=11)
        _pdf_write_lines(pdf, _plain_lines_from_markdown(enhanced_notes_md))
        pdf.ln(2)
    if notes_text.strip():
        pdf.set_font("Helvetica", "B", 13)
        pdf.multi_cell(pdf.epw, 7, "My Notes")
        pdf.set_font("Helvetica", size=11)
        _pdf_write_lines(pdf, [line.strip() for line in notes_text.splitlines() if line.strip()])
        pdf.ln(2)
    if segments:
        pdf.set_font("Helvetica", "B", 13)
        pdf.multi_cell(pdf.epw, 7, "Transcript")
        pdf.set_font("Helvetica", size=11)
        for segment in segments:
            speaker = resolve_speaker_label(segment.speaker_id, identity)
            pdf.multi_cell(pdf.epw, 6, _pdf_safe(f"{speaker}: {segment.text}"))
            pdf.ln(2)
    return pdf.output()


def export_meeting_docx(
    title: str,
    notes_text: str,
    enhanced_notes_md: str,
    segments: list[TranscriptSegmentRow],
    identity: str = "Me",
) -> bytes:
    from docx import Document

    document = Document()
    document.add_heading(title, level=0)
    if enhanced_notes_md.strip():
        document.add_heading("Enhanced Notes", level=1)
        for line in _plain_lines_from_markdown(enhanced_notes_md):
            if line:
                document.add_paragraph(line)
    if notes_text.strip():
        document.add_heading("My Notes", level=1)
        for line in notes_text.splitlines():
            if line.strip():
                document.add_paragraph(line.strip())
    if segments:
        document.add_heading("Transcript", level=1)
        for segment in segments:
            speaker = resolve_speaker_label(segment.speaker_id, identity)
            document.add_paragraph(f"{speaker}: {segment.text}")
    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()
