"""Transcode a finished capture WAV to MP3 via ffmpeg (kept-audio format).

Purpose: the ONE place kept audio is converted from the crash-safe WAV that
:class:`engine.stt.keep_audio_recorder.KeepAudioRecorder` streams to disk into
the compact MP3 the user keeps alongside the transcript. Pure, synchronous,
and fail-soft: if ffmpeg is missing or the transcode fails, it returns ``None``
and the caller keeps the WAV — audio is never lost to an encoding problem.

Pipeline position: called at capture-session ``close``, after the WAV header is
finalised; the successful MP3 replaces the WAV as the retained copy.

Security invariant (claude.md §5.6 local-only binding):
- ffmpeg runs fully offline on a local file — no network, no upload; encoding
  never sends audio anywhere.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)

# 128 kbps CBR mono: small files, transparent for speech, and a widely-playable
# baseline. Kept audio is a convenience artifact for the user, not a master.
_MP3_BITRATE = "128k"
_FFMPEG_TIMEOUT_S = 300


def encode_wav_to_mp3(wav_path: Path) -> Path | None:
    """Transcode ``wav_path`` to a sibling ``.mp3``; return it, or ``None`` on failure.

    Fail-soft (audio > file): a missing ffmpeg, a non-zero exit, a timeout, a
    raised OS/subprocess error, or a missing output all return ``None`` so the
    caller retains the WAV instead of losing the recording.
    """
    if shutil.which("ffmpeg") is None:
        # Fail-soft: no encoder available, keep the WAV as the retained copy.
        logger.warning("keep-audio: ffmpeg not found; keeping WAV instead of MP3")
        return None
    mp3_path = wav_path.with_suffix(".mp3")
    try:
        result = subprocess.run(  # noqa: S603 - fixed argv, ffmpeg guarded by shutil.which; no untrusted input
            [  # noqa: S607 - ffmpeg resolved via PATH (offline, local-only)
                "ffmpeg",
                "-nostdin",
                "-y",  # overwrite: a stale partial from a crash must not block
                "-i",
                str(wav_path),
                "-codec:a",
                "libmp3lame",
                "-b:a",
                _MP3_BITRATE,
                "-ac",
                "1",  # capture is mono; keep the MP3 mono
                str(mp3_path),
            ],
            capture_output=True,
            check=False,
            timeout=_FFMPEG_TIMEOUT_S,
        )
    except (OSError, subprocess.SubprocessError):
        # Fail-soft: any invocation failure keeps the WAV (never raise).
        logger.exception("keep-audio: ffmpeg invocation failed; keeping WAV")
        return None
    if result.returncode != 0 or not mp3_path.is_file():
        detail = (result.stderr or b"").decode("utf-8", errors="replace")[-400:]
        logger.warning("keep-audio: ffmpeg could not encode %s: %s", wav_path.name, detail)
        return None
    return mp3_path
