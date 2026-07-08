"""Platform-selected capture backend factory."""

from __future__ import annotations

import sys

from engine.audio.dual_stream_capture_controller import CaptureBackend


def create_capture_backend() -> CaptureBackend:
    """Return the production capture backend for the current platform."""
    if sys.platform == "win32":
        from engine.audio.pyaudiowpatch_capture_backend import PyAudioWpatchCaptureBackend

        return PyAudioWpatchCaptureBackend()
    raise RuntimeError(
        f"capture is not yet supported on {sys.platform} — Windows is fully supported today"
    )
