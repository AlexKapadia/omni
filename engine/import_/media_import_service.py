"""Media file import — decode with ffmpeg and transcribe offline."""

from __future__ import annotations

import asyncio
import shutil
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from pathlib import Path

import aiosqlite

from engine.stt.file_diarization_service import assign_speakers_to_segments
from engine.stt.offline_audio_transcriber import decode_media_to_mono_16k, new_segment_id
from engine.stt.stt_backend_protocol import SttSegment
from engine.stt.stt_settings_loader import load_stt_backend_from_settings
from engine.storage.meetings_repository import insert_meeting, mark_meeting_ended
from engine.storage.sqlite_connection import open_sqlite_connection
from engine.storage.sqlite_migrations_runner import apply_migrations
from engine.storage.transcript_segments_repository import insert_transcript_segment

ProgressFn = Callable[[str, float], Awaitable[None] | None]


def _utc_now_iso() -> str:
    return datetime.now(tz=UTC).isoformat()


async def _emit_progress(callback: ProgressFn | None, stage: str, fraction: float) -> None:
    if callback is None:
        return
    result = callback(stage, fraction)
    if result is not None:
        await result


async def import_media_file(
    db_path: Path,
    migrations_dir: Path,
    media_path: str,
    title: str | None,
    *,
    models_dir: Path | None = None,
    identify_speakers: bool = False,
    on_progress: ProgressFn | None = None,
) -> str:
    """Create a meeting from a local audio/video file with full STT."""
    source = Path(media_path)
    if not source.is_file():
        raise ValueError(f"file not found: {media_path}")
    if shutil.which("ffmpeg") is None:
        raise ValueError("ffmpeg is not installed — install ffmpeg to import media files")

    meeting_id = str(uuid.uuid4())
    meeting_title = title.strip() if title and title.strip() else source.stem
    started_at = _utc_now_iso()

    await _emit_progress(on_progress, "decoding", 0.1)
    samples = await asyncio.to_thread(decode_media_to_mono_16k, source)
    await apply_migrations(db_path, migrations_dir)
    connection = await open_sqlite_connection(db_path)
    try:
        await _emit_progress(on_progress, "transcribing", 0.35)
        backend = await load_stt_backend_from_settings(connection, models_dir=models_dir)
        segments: list[SttSegment] = await asyncio.to_thread(
            backend.transcribe_samples, samples, stream="them"
        )
        if identify_speakers and segments:
            await _emit_progress(on_progress, "diarizing", 0.75)
            labeled = await asyncio.to_thread(assign_speakers_to_segments, samples, segments)
        else:
            labeled = [(segment, "1", "Speaker 1") for segment in segments]

        ended_at = _utc_now_iso()

        await _emit_progress(on_progress, "saving", 0.9)
        await insert_meeting(connection, meeting_id, meeting_title, started_at)
        await mark_meeting_ended(connection, meeting_id, ended_at)
        created_at = _utc_now_iso()
        if not labeled:
            await insert_transcript_segment(
                connection,
                segment_id=new_segment_id(),
                meeting_id=meeting_id,
                stream="them",
                speaker_id="1",
                text="[No speech detected in imported file.]",
                t_start=0.0,
                t_end=max(1.0, samples.size / 16_000),
                created_at_iso=created_at,
            )
        else:
            for segment, speaker_id, _label in labeled:
                await insert_transcript_segment(
                    connection,
                    segment_id=new_segment_id(),
                    meeting_id=meeting_id,
                    stream=segment.stream,
                    speaker_id=speaker_id,
                    text=segment.text,
                    t_start=segment.t_start,
                    t_end=segment.t_end,
                    created_at_iso=created_at,
                )
        await connection.commit()
    finally:
        await connection.close()
    await _emit_progress(on_progress, "done", 1.0)
    return meeting_id
