"""Detect whether a meeting still has kept me/them audio on disk.

Used by ``meeting.get`` so the Library can hide Retranscribe when there is
nothing to re-run. Checks the keep-audio session dir for ``me``/``them``
``.mp3`` or ``.wav`` files (same resolution as retranscription).
"""

from __future__ import annotations

from pathlib import Path

from engine.audio.audio_frame_types import StreamLabel
from engine.enhance.meeting_retranscription_service import resolve_kept_audio_path
from engine.stt.keep_audio_recorder import keep_audio_directory


def meeting_has_kept_audio(
    meeting_id: str, *, audio_root: Path | None = None
) -> bool:
    """True when at least one me/them mp3|wav exists for this meeting."""
    root = audio_root if audio_root is not None else keep_audio_directory()
    session_dir = root / meeting_id
    if not session_dir.is_dir():
        return False
    for label in (StreamLabel.THEM, StreamLabel.ME):
        if resolve_kept_audio_path(session_dir, label) is not None:
            return True
    return False
