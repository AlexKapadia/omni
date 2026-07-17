"""Platform-selected capture backend factory."""

from __future__ import annotations

import sys

from engine.audio.dual_stream_capture_controller import CaptureBackend


def create_capture_backend() -> CaptureBackend:
    """Return the production capture backend for the current platform."""
    # Bind to str so mypy does not treat non-host branches as unreachable.
    platform_name: str = sys.platform
    if platform_name == "win32":
        from engine.audio.pyaudiowpatch_capture_backend import PyAudioWpatchCaptureBackend

        return PyAudioWpatchCaptureBackend()
    if platform_name == "darwin" or platform_name.startswith("linux"):
        from engine.audio.sounddevice_capture_backend import SoundDeviceCaptureBackend

        return SoundDeviceCaptureBackend()
    raise RuntimeError(f"capture is not yet supported on {platform_name}")
