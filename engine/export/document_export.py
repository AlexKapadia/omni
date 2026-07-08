"""PDF and DOCX transcript export."""

from __future__ import annotations

import io
from typing import Literal

from engine.storage.transcript_segments_repository import TranscriptSegmentRow

ExportBinaryFormat = Literal["pdf", "docx"]


def export_transcript_pdf(segments: list[TranscriptSegmentRow]) -> bytes:
    from fpdf import FPDF

    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()
    pdf.set_font("Helvetica", size=11)
    for segment in segments:
        speaker = "Me" if segment.stream == "me" else "Them"
        line = f"{speaker}: {segment.text}"
        pdf.multi_cell(0, 6, line)
        pdf.ln(2)
    return pdf.output()


def export_transcript_docx(segments: list[TranscriptSegmentRow]) -> bytes:
    from docx import Document

    document = Document()
    document.add_heading("Meeting transcript", level=1)
    for segment in segments:
        speaker = "Me" if segment.stream == "me" else "Them"
        document.add_paragraph(f"{speaker}: {segment.text}")
    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()
