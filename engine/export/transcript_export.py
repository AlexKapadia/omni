"""Transcript export helpers — SRT, VTT, and plain text."""

from __future__ import annotations

from engine.storage.transcript_segments_repository import TranscriptSegmentRow
from engine.stt.speaker_voice_profile import resolve_speaker_label


def _format_srt_timestamp(seconds: float) -> str:
    total_ms = max(0, int(seconds * 1000))
    hours = total_ms // 3_600_000
    minutes = (total_ms % 3_600_000) // 60_000
    secs = (total_ms % 60_000) // 1000
    millis = total_ms % 1000
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def _format_vtt_timestamp(seconds: float) -> str:
    return _format_srt_timestamp(seconds).replace(",", ".")


def export_transcript_srt(segments: list[TranscriptSegmentRow], identity: str = "Me") -> str:
    lines: list[str] = []
    for index, segment in enumerate(segments, start=1):
        speaker = resolve_speaker_label(segment.speaker_id, identity)
        lines.append(str(index))
        lines.append(
            f"{_format_srt_timestamp(segment.t_start)} --> {_format_srt_timestamp(segment.t_end)}"
        )
        lines.append(f"{speaker}: {segment.text}")
        lines.append("")
    return "\n".join(lines).strip() + ("\n" if lines else "")


def export_transcript_vtt(segments: list[TranscriptSegmentRow], identity: str = "Me") -> str:
    lines = ["WEBVTT", ""]
    for segment in segments:
        speaker = resolve_speaker_label(segment.speaker_id, identity)
        lines.append(
            f"{_format_vtt_timestamp(segment.t_start)} --> {_format_vtt_timestamp(segment.t_end)}"
        )
        lines.append(f"{speaker}: {segment.text}")
        lines.append("")
    return "\n".join(lines).strip() + "\n"


def export_transcript_txt(segments: list[TranscriptSegmentRow], identity: str = "Me") -> str:
    return "\n".join(
        f"{resolve_speaker_label(s.speaker_id, identity)}: {s.text}" for s in segments
    )


def export_meeting_markdown(
    title: str,
    notes_text: str,
    enhanced_notes_md: str,
    segments: list[TranscriptSegmentRow],
    identity: str = "Me",
) -> str:
    """Full meeting export: enhanced notes, rough notes, and transcript."""
    parts: list[str] = [f"# {title}", ""]
    if enhanced_notes_md.strip():
        parts.extend(["## Enhanced Notes", "", enhanced_notes_md.strip(), ""])
    if notes_text.strip():
        parts.extend(["## My Notes", "", notes_text.strip(), ""])
    if segments:
        parts.extend(["## Transcript", ""])
        for segment in segments:
            speaker = resolve_speaker_label(segment.speaker_id, identity)
            parts.append(f"**{speaker}:** {segment.text}")
        parts.append("")
    return "\n".join(parts).strip() + "\n"
