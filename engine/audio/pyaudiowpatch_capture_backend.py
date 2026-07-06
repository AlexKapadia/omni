"""Production capture backend: pyaudiowpatch (PortAudio + WASAPI loopback).

Purpose: implements ``engine.audio.dual_stream_capture_controller.CaptureBackend``
on real Windows hardware — probes the CURRENT default render device's
WASAPI loopback ("them") and the default microphone ("me"), and opens
callback-driven int16 capture streams on them.

WHY a fresh PyAudio instance per probe: PortAudio freezes its device list
and default-device indices at ``Pa_Initialize``. Re-instantiating per
probe (~tens of ms, off the event loop) is the reliable way to observe a
default-device change; instances are refcounted so this is safe alongside
open streams.

Pipeline position: the hardware edge of the capture path; everything above
it is testable with fake backends.

Security invariant: raw audio goes straight to the controller callback and
is never persisted or logged here (local-only invariant).
"""

import contextlib
import time
from collections.abc import Callable
from typing import Any

from engine.audio.audio_frame_types import StreamLabel
from engine.audio.dual_stream_capture_controller import CaptureDeviceSpec

# ~20 ms callback chunks: small enough for low latency, large enough that
# the callback rate (50/s) costs nothing.
_CHUNK_SECONDS = 0.02
_MIN_FRAMES_PER_BUFFER = 128


def _spec_from_device_info(info: dict[str, Any]) -> CaptureDeviceSpec:
    """Map a PortAudio device-info dict to our typed spec.

    ``key`` combines index and name: PortAudio may reuse an index after a
    topology change, and names alone can collide (two identical headsets),
    so the pair is the stable-enough identity for change detection.
    """
    return CaptureDeviceSpec(
        key=f"{info['index']}:{info['name']}",
        name=str(info["name"]),
        sample_rate=int(info["defaultSampleRate"]),
        channels=max(1, int(info["maxInputChannels"])),
    )


class _PyAudioStreamHandle:
    """Owns one PyAudio instance + one open stream; closes both together."""

    def __init__(self, pyaudio_instance: Any, stream: Any) -> None:
        self._pyaudio = pyaudio_instance
        self._stream = stream
        self._closed = False

    @property
    def is_alive(self) -> bool:
        """False once the device stalls/vanishes (PortAudio deactivates it)."""
        if self._closed:
            return False
        try:
            return bool(self._stream.is_active())
        except OSError:
            return False  # Stream torn down under us — treat as dead.

    def close(self) -> None:
        """Stop and release stream + PortAudio instance (idempotent)."""
        if self._closed:
            return
        self._closed = True
        for step in (self._stream.stop_stream, self._stream.close, self._pyaudio.terminate):
            # Device may already be gone; releasing the rest still matters.
            with contextlib.suppress(OSError):
                step()


class PyAudioWpatchCaptureBackend:
    """Real-hardware ``CaptureBackend`` backed by pyaudiowpatch."""

    def probe_default_device(self, stream: StreamLabel) -> CaptureDeviceSpec:
        """Return the current default endpoint for the stream label.

        ``them``: the WASAPI loopback twin of the default render device —
        this is what makes capture headphone-proof (we tap the render mix,
        not a microphone picking up speakers).
        ``me``: the default input device (microphone).
        """
        import pyaudiowpatch as pyaudio  # Lazy: Windows-only dependency.

        instance = pyaudio.PyAudio()  # Fresh instance -> fresh default-device view.
        try:
            if stream is StreamLabel.THEM:
                info = instance.get_default_wasapi_loopback()
            else:
                info = instance.get_default_input_device_info()
            return _spec_from_device_info(dict(info))
        finally:
            instance.terminate()

    def open_capture_stream(
        self, spec: CaptureDeviceSpec, on_chunk: Callable[[bytes, float], None]
    ) -> _PyAudioStreamHandle:
        """Open a callback-driven int16 capture stream on ``spec``."""
        import pyaudiowpatch as pyaudio  # Lazy: Windows-only dependency.

        device_index = int(spec.key.split(":", 1)[0])
        instance = pyaudio.PyAudio()

        def callback(
            in_data: bytes | None, frame_count: int, time_info: Any, status: Any
        ) -> tuple[None, int]:
            # time.monotonic() here is "just after the last sample" — the
            # shared clock that lets the controller stitch continuity by
            # time across device changes.
            if in_data:
                on_chunk(in_data, time.monotonic())
            return (None, pyaudio.paContinue)

        try:
            stream = instance.open(
                format=pyaudio.paInt16,
                channels=spec.channels,
                rate=spec.sample_rate,
                frames_per_buffer=max(
                    _MIN_FRAMES_PER_BUFFER, int(spec.sample_rate * _CHUNK_SECONDS)
                ),
                input=True,
                input_device_index=device_index,
                stream_callback=callback,
            )
        except OSError:
            instance.terminate()  # Fail closed: no orphaned PortAudio refs.
            raise
        return _PyAudioStreamHandle(instance, stream)
