"""Re-transcribe a meeting from kept audio (MP3 preferred, WAV fallback)."""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import numpy.typing as npt

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
    decode_media_to_mono_16k,
    decode_wav_to_mono_16k,
    new_segment_id,
    transcribe_samples_with_backend,
)
from engine.stt.stt_settings_loader import load_stt_backend_from_settings

logger = logging.getLogger(__name__)


def _utc_now_iso() -> str:
    return datetime.now(tz=UTC).isoformat()


def resolve_kept_audio_path(session_dir: Path, label: StreamLabel) -> Path | None:
    """Prefer ``{label}.mp3`` (post keep-audio encode), else ``{label}.wav``."""
    mp3_path = session_dir / f"{label.value}.mp3"
    if mp3_path.is_file():
        return mp3_path
    wav_path = session_dir / f"{label.value}.wav"
    if wav_path.is_file():
        return wav_path
    return None


def decode_kept_audio(path: Path) -> npt.NDArray[np.float32]:
    """Decode kept audio: WAV via wave module; anything else via ffmpeg."""
    if path.suffix.lower() == ".wav":
        return decode_wav_to_mono_16k(path)
    return decode_media_to_mono_16k(path)


async def retranscribe_meeting(
    db_path: Path,
    migrations_dir: Path,
    meeting_id: str,
    *,
    models_dir: Path | None = None,
) -> None:
    """Replace transcript segments using retained them/me MP3 or WAV files."""
    await apply_migrations(db_path, migrations_dir)
    connection = await open_sqlite_connection(db_path)
    try:
        row = await fetch_meeting_row(connection, meeting_id)
        if row is None:
            raise ValueError(f"meeting {meeting_id!r} does not exist")
        if row.ended_at is None:
            raise ValueError("cannot retranscribe a live meeting")
        backend = await load_stt_backend_from_settings(connection, models_dir=models_dir)
        session_dir = keep_audio_directory() / meeting_id
        all_segments = []
        for label in (StreamLabel.THEM, StreamLabel.ME):
            audio_path = resolve_kept_audio_path(session_dir, label)
            if audio_path is None:
                logger.warning(
                    "retranscribe: missing %s.mp3/%s.wav for %s",
                    label.value,
                    label.value,
                    meeting_id,
                )
                continue
            samples = await asyncio.to_thread(decode_kept_audio, audio_path)
            all_segments.extend(
                await asyncio.to_thread(
                    transcribe_samples_with_backend,
                    backend,
                    samples,
                    stream=label.value,
                )
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
                speaker_id="1" if segment.stream == "them" else "me",
                text=segment.text,
                t_start=segment.t_start,
                t_end=segment.t_end,
                created_at_iso=created_at,
            )
        await connection.commit()
    finally:
        await connection.close()
