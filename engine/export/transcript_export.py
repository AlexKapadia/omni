"""Transcript export helpers — SRT, VTT, and plain text."""

from __future__ import annotations

from engine.storage.transcript_segments_repository import TranscriptSegmentRow


def _format_srt_timestamp(seconds: float) -> str:
    total_ms = max(0, int(seconds * 1000))
    hours = total_ms // 3_600_000
    minutes = (total_ms % 3_600_000) // 60_000
    secs = (total_ms % 60_000) // 1000
    millis = total_ms % 1000
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def _format_vtt_timestamp(seconds: float) -> str:
    return _format_srt_timestamp(seconds).replace(",", ".")


def export_transcript_srt(segments: list[TranscriptSegmentRow]) -> str:
    lines: list[str] = []
    for index, segment in enumerate(segments, start=1):
        speaker = "Me" if segment.stream == "me" else "Them"
        lines.append(str(index))
        lines.append(
            f"{_format_srt_timestamp(segment.t_start)} --> {_format_srt_timestamp(segment.t_end)}"
        )
        lines.append(f"{speaker}: {segment.text}")
        lines.append("")
    return "\n".join(lines).strip() + ("\n" if lines else "")


def export_transcript_vtt(segments: list[TranscriptSegmentRow]) -> str:
    lines = ["WEBVTT", ""]
    for segment in segments:
        speaker = "Me" if segment.stream == "me" else "Them"
        lines.append(
            f"{_format_vtt_timestamp(segment.t_start)} --> {_format_vtt_timestamp(segment.t_end)}"
        )
        lines.append(f"{speaker}: {segment.text}")
        lines.append("")
    return "\n".join(lines).strip() + "\n"


def export_transcript_txt(segments: list[TranscriptSegmentRow]) -> str:
    return "\n".join(
        f"{'Me' if s.stream == 'me' else 'Them'}: {s.text}" for s in segments
    )
