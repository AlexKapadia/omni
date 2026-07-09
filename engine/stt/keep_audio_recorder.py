"""Raw-audio retention: per-stream files kept alongside the transcript.

Purpose: the ONE place captured audio is ever written to disk. Retention is ON
by default (the user wants recordings kept, not discarded); each capture
session's two streams are streamed to 16 kHz mono PCM WAV — crash-safe, since
WAV can be appended incrementally — and, on session close, transcoded to a
compact **MP3** that replaces the WAV as the retained copy. Files land in a
user-private directory, never the vault, never a network path.
Pipeline position: fed by ``engine.stt.live_capture_service._drain_loop``
alongside the transcription pipelines; closed (and MP3-encoded) at ``stop``.

Security invariants (claude.md §5.6 local-only binding):
- Audio never leaves the machine: files land under ``%LOCALAPPDATA%/Omni/
  audio`` (overridable via ``OMNI_AUDIO_DIR``), never the vault, never a
  network path. MP3 encoding runs ffmpeg fully offline (no upload).
- Retention follows the persisted ``keep_audio`` setting; it is only skipped
  when that setting is exactly ``False`` — :func:`create_keep_audio_recorder_if_enabled`
  reads it (default ``True``) and returns ``None`` only on an explicit opt-out.
- Fail-soft: a write error disables retention for the session and logs, and a
  failed/absent MP3 encode keeps the WAV — audio retention must never take a
  live capture down, and a format problem must never lose the recording.
"""

import logging
import os
import wave
from collections.abc import Callable
from pathlib import Path

import aiosqlite
import numpy as np

from engine.audio.audio_frame_types import PIPELINE_SAMPLE_RATE, AudioFrame, StreamLabel
from engine.audio.wav_to_mp3_encoder import encode_wav_to_mp3
from engine.storage.app_settings_repository import SETTING_KEEP_AUDIO, read_setting_bool

logger = logging.getLogger(__name__)

# 16-bit PCM: the on-disk format for the kept audio (Silero/Parakeet run on
# float32 in memory; the saved file is standard, playable int16 WAV).
_PCM_SAMPLE_WIDTH_BYTES = 2
_INT16_FULL_SCALE = 32767


def keep_audio_directory() -> Path:
    """Resolve the audio directory: OMNI_AUDIO_DIR or %LOCALAPPDATA%/Omni/audio."""
    override = os.environ.get("OMNI_AUDIO_DIR")
    if override:
        return Path(override)
    local_app_data = os.environ.get("LOCALAPPDATA")
    base = Path(local_app_data) if local_app_data else Path.home() / ".local" / "share"
    return base / "Omni" / "audio"


class KeepAudioRecorder:
    """Writes one file per stream for a single capture session (WAV → MP3).

    Each stream is streamed to WAV as frames arrive (crash-safe append), then
    transcoded to MP3 on :meth:`close`. Writers are opened lazily on the first
    frame of each stream, so a stream that never produced audio leaves no file.
    The MP3 encoder is injected for testability; it defaults to the real
    ffmpeg-backed :func:`encode_wav_to_mp3`.
    """

    def __init__(
        self,
        session_dir: Path,
        encoder: Callable[[Path], Path | None] = encode_wav_to_mp3,
    ) -> None:
        self._session_dir = session_dir
        self._encoder = encoder
        self._writers: dict[StreamLabel, wave.Wave_write] = {}
        self._disabled = False  # flips True on the first write error (fail-soft)

    def write_frame(self, frame: AudioFrame) -> None:
        """Append one frame's audio to its stream's WAV file (fail-soft)."""
        if self._disabled:
            return
        try:
            writer = self._writer_for(frame.stream)
            # float32 [-1, 1] -> int16 PCM: clip first so a stray out-of-range
            # sample can never wrap to the opposite polarity (a loud click).
            clipped = np.clip(frame.samples, -1.0, 1.0)
            pcm16 = (clipped * _INT16_FULL_SCALE).astype("<i2")
            writer.writeframes(pcm16.tobytes())
        except Exception:
            # Retention is best-effort: disable it for this session and keep
            # capturing (audio > file). Loud in the log, silent to the user.
            logger.exception("keep-audio: write failed; disabling retention for this session")
            self._disabled = True
            self.close()

    def _writer_for(self, stream: StreamLabel) -> wave.Wave_write:
        writer = self._writers.get(stream)
        if writer is None:
            self._session_dir.mkdir(parents=True, exist_ok=True)
            # The writer deliberately OUTLIVES this method: it spans the whole
            # session and is finalised in close(), so a `with` cannot express
            # its lifecycle (SIM115 suppressed for that reason).
            writer = wave.open(  # noqa: SIM115
                str(self._session_dir / f"{stream.value}.wav"), "wb"
            )
            writer.setnchannels(1)  # mono
            writer.setsampwidth(_PCM_SAMPLE_WIDTH_BYTES)  # 16-bit
            writer.setframerate(PIPELINE_SAMPLE_RATE)  # 16 kHz
            self._writers[stream] = writer
        return writer

    def close(self) -> None:
        """Finalise each WAV, then transcode it to MP3 (removing the WAV)."""
        for stream, writer in self._writers.items():
            # Attempt EVERY writer; one failure must not strand the others.
            try:
                writer.close()  # writes the WAV header lengths
            except Exception:
                logger.exception("keep-audio: closing a WAV writer failed")
                continue  # a broken WAV is left as-is, never transcoded
            self._finalize_as_mp3(self._session_dir / f"{stream.value}.wav")
        self._writers = {}

    def _finalize_as_mp3(self, wav_path: Path) -> None:
        """Replace a finalised WAV with an MP3; keep the WAV if encoding fails."""
        try:
            mp3_path = self._encoder(wav_path)
        except Exception:
            # Fail-soft: an encoder crash must never lose the recording.
            logger.exception("keep-audio: MP3 encode raised; keeping WAV")
            return
        if mp3_path is None:
            return  # ffmpeg missing/failed: the WAV stays as the kept audio
        try:
            wav_path.unlink(missing_ok=True)  # MP3 is the kept copy; drop the WAV
        except OSError:
            logger.warning("keep-audio: could not remove WAV after MP3 encode")


async def create_keep_audio_recorder_if_enabled(
    connection: aiosqlite.Connection,
    meeting_id: str,
    audio_dir: Path | None = None,
) -> KeepAudioRecorder | None:
    """Return a recorder unless ``keep_audio`` is persisted exactly False.

    Retention is ON by default: a missing/unset/wrong-typed setting keeps audio
    (the user wants recordings saved). Only an explicit ``False`` opts out. A
    read error also opts out — retention is best-effort and never blocks capture.
    """
    try:
        enabled = await read_setting_bool(connection, SETTING_KEEP_AUDIO, default=True)
    except Exception:
        # Best-effort: if the setting is unreadable, skip retention rather than
        # risk taking capture down over an audio-file convenience feature.
        logger.exception("keep-audio: could not read the setting; skipping retention")
        return None
    if not enabled:
        return None
    base = audio_dir if audio_dir is not None else keep_audio_directory()
    # keep-audio opt-in honoured: retained audio is user-private and local only.
    return KeepAudioRecorder(base / meeting_id)
