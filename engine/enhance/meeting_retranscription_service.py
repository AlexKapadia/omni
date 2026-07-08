"""Re-transcribe a meeting from kept WAV files (keep_audio opt-in)."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path

from engine.audio.audio_frame_types import StreamLabel
from engine.storage.meetings_repository import fetch_meeting_row
from engine.storage.sqlite_connection import open_sqlite_connection
from engine.storage.sqlite_migrations_runner import apply_migrations
from engine.storage.transcript_segments_repository import (
    delete_transcript_segments_for_meeting,
    insert_transcript_segment,
)
from engine.stt.keep_audio_recorder import keep_audio_directory
from engine.stt.offline_audio_transcriber import (
    decode_wav_to_mono_16k,
    load_transcriber,
    new_segment_id,
    transcribe_samples,
)

logger = logging.getLogger(__name__)


def _utc_now_iso() -> str:
    return datetime.now(tz=UTC).isoformat()


async def retranscribe_meeting(
    db_path: Path,
    migrations_dir: Path,
    meeting_id: str,
    *,
    models_dir: Path | None = None,
) -> None:
    """Replace transcript segments using retained them/me WAV files."""
    await apply_migrations(db_path, migrations_dir)
    connection = await open_sqlite_connection(db_path)
    try:
        row = await fetch_meeting_row(connection, meeting_id)
        if row is None:
            raise ValueError(f"meeting {meeting_id!r} does not exist")
        if row.ended_at is None:
            raise ValueError("cannot retranscribe a live meeting")
        session_dir = keep_audio_directory() / meeting_id
        transcriber = load_transcriber(models_dir or keep_audio_directory())
        all_segments = []
        for label in (StreamLabel.THEM, StreamLabel.ME):
            wav_path = session_dir / f"{label.value}.wav"
            if not wav_path.is_file():
                logger.warning("retranscribe: missing %s for %s", wav_path.name, meeting_id)
                continue
            samples = decode_wav_to_mono_16k(wav_path)
            all_segments.extend(
                transcribe_samples(transcriber, samples, stream=label.value)
            )
        if not all_segments:
            raise ValueError("no kept audio found for this meeting")
        await delete_transcript_segments_for_meeting(connection, meeting_id)
        created_at = _utc_now_iso()
        for segment in sorted(all_segments, key=lambda s: (s.t_start, s.stream)):
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
