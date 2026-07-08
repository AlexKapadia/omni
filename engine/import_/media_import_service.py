"""Media file import — decode with ffmpeg and transcribe offline."""

from __future__ import annotations

import shutil
import uuid
from datetime import UTC, datetime
from pathlib import Path

from engine.storage.meetings_repository import insert_meeting, mark_meeting_ended
from engine.storage.sqlite_connection import open_sqlite_connection
from engine.storage.sqlite_migrations_runner import apply_migrations
from engine.storage.transcript_segments_repository import insert_transcript_segment
from engine.stt.offline_audio_transcriber import (
    decode_media_to_mono_16k,
    load_transcriber,
    new_segment_id,
    transcribe_samples,
)


def _utc_now_iso() -> str:
    return datetime.now(tz=UTC).isoformat()


async def import_media_file(
    db_path: Path,
    migrations_dir: Path,
    media_path: str,
    title: str | None,
    *,
    models_dir: Path | None = None,
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

    samples = decode_media_to_mono_16k(source)
    transcriber = load_transcriber(models_dir)
    segments = transcribe_samples(transcriber, samples, stream="them")

    await apply_migrations(db_path, migrations_dir)
    connection = await open_sqlite_connection(db_path)
    try:
        await insert_meeting(connection, meeting_id, meeting_title, started_at)
        await mark_meeting_ended(connection, meeting_id, started_at)
        created_at = _utc_now_iso()
        if not segments:
            await insert_transcript_segment(
                connection,
                segment_id=new_segment_id(),
                meeting_id=meeting_id,
                stream="them",
                text="[No speech detected in imported file.]",
                t_start=0.0,
                t_end=max(1.0, samples.size / 16_000),
                created_at_iso=created_at,
            )
        else:
            for segment in segments:
                await insert_transcript_segment(
                    connection,
                    segment_id=new_segment_id(),
                    meeting_id=meeting_id,
                    stream=segment.stream,
                    text=segment.text,
                    t_start=segment.t_start,
                    t_end=segment.t_end,
                    created_at_iso=created_at,
                )
        await connection.commit()
    finally:
        await connection.close()
    return meeting_id
