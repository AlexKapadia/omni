"""Opt-in raw-audio retention: per-stream WAV files, ONLY when the user asked.

Purpose: the ONE place captured audio is ever written to disk. By default it
is never constructed — audio is discarded after transcription (local-only
invariant). It exists solely to honour the explicit ``keep_audio`` setting
(default OFF): when the user opts in, each capture session's two streams are
saved as 16 kHz mono PCM WAV files under a user-private directory.
Pipeline position: fed by ``engine.stt.live_capture_service._drain_loop``
alongside the transcription pipelines; closed at ``stop``.

Security invariants (claude.md §5.6 local-only binding):
- Audio never leaves the machine: files land under ``%LOCALAPPDATA%/Omni/
  audio`` (overridable via ``OMNI_AUDIO_DIR``), never the vault, never a
  network path.
- Retention is OFF unless the persisted ``keep_audio`` setting is exactly
  ``True`` — :func:`create_keep_audio_recorder_if_enabled` reads it and
  returns ``None`` on anything else (deny by default: no accidental keep).
- Fail-soft: a write error disables retention for the session and logs —
  audio retention must never take a live capture down.
"""

import logging
import os
import wave
from pathlib import Path

import aiosqlite
import numpy as np

from engine.audio.audio_frame_types import PIPELINE_SAMPLE_RATE, AudioFrame, StreamLabel
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
    """Writes one WAV file per stream for a single capture session.

    Writers are opened lazily on the first frame of each stream, so a stream
    that never produced audio leaves no empty file.
    """

    def __init__(self, session_dir: Path) -> None:
        self._session_dir = session_dir
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
        """Finalise every open WAV file (writes the header lengths)."""
        for writer in self._writers.values():
            # Attempt EVERY writer; one failure must not strand the others.
            try:
                writer.close()
            except Exception:
                logger.exception("keep-audio: closing a WAV writer failed")
        self._writers = {}


async def create_keep_audio_recorder_if_enabled(
    connection: aiosqlite.Connection,
    meeting_id: str,
    audio_dir: Path | None = None,
) -> KeepAudioRecorder | None:
    """Return a recorder ONLY when ``keep_audio`` is persisted True.

    Deny by default: a missing/False/wrong-typed setting yields ``None`` and
    audio is discarded as usual. Any read error is treated as "not enabled".
    """
    try:
        enabled = await read_setting_bool(connection, SETTING_KEEP_AUDIO, default=False)
    except Exception:
        # Fail closed on the retention decision: unreadable => do not keep.
        logger.exception("keep-audio: could not read the setting; retention stays off")
        return None
    if not enabled:
        return None
    base = audio_dir if audio_dir is not None else keep_audio_directory()
    # keep-audio opt-in honoured: retained audio is user-private and local only.
    return KeepAudioRecorder(base / meeting_id)
