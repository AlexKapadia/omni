"""Tests for transcript export formats."""

from engine.export.transcript_export import export_transcript_srt, export_transcript_vtt
from engine.storage.transcript_segments_repository import TranscriptSegmentRow


def test_export_srt_includes_timestamps() -> None:
    segments = [
        TranscriptSegmentRow("s1", "them", "Hello", 0.0, 2.5),
        TranscriptSegmentRow("s2", "me", "Hi", 2.5, 4.0),
    ]
    srt = export_transcript_srt(segments)
    assert "00:00:00,000 --> 00:00:02,500" in srt
    assert "Them: Hello" in srt
    assert "Me: Hi" in srt


def test_export_vtt_header() -> None:
    segments = [TranscriptSegmentRow("s1", "them", "Test", 1.0, 2.0)]
    vtt = export_transcript_vtt(segments)
    assert vtt.startswith("WEBVTT")
