"""Linux PipeWire capture stub — implement monitor streams in Phase 6 hardware pass."""

from __future__ import annotations

from engine.audio.dual_stream_capture_controller import CaptureStreamHandle


class PipewireCaptureBackend:
  def probe_default_device(self) -> str:
    raise RuntimeError("Linux PipeWire capture is not yet available on this build")

  def open_capture_stream(self, device_name: str, on_frames) -> CaptureStreamHandle:
    raise RuntimeError("Linux PipeWire capture is not yet available on this build")
