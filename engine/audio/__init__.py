"""Dual-stream local audio capture for the Omni engine.

Purpose: captures two labelled audio streams simultaneously — WASAPI
loopback of the default render device (label ``them``: the other meeting
participants, headphone-proof) and the default microphone (label ``me``) —
resamples everything to 16 kHz mono, and hands timestamped frames to the
STT layer through a bounded ring buffer.
Pipeline position: the very first stage of the meeting-intelligence
pipeline; ``engine.stt`` consumes what this package produces.

Security invariants:
- Audio NEVER leaves the machine and is NEVER written to disk by this
  package: frames live only in memory and are discarded after
  transcription (local-only invariant; keep-audio toggle is a later,
  opt-in feature — default off).
- No telemetry: device names stay local except when the UI is explicitly
  told about a device change over the loopback-only WebSocket.
"""

from engine.audio.audio_frame_types import PIPELINE_SAMPLE_RATE, AudioFrame, StreamLabel
from engine.audio.dual_stream_capture_controller import (
    CaptureBackend,
    CaptureDeviceSpec,
    CaptureStreamHandle,
    DualStreamCaptureController,
)
from engine.audio.resample_to_16k_mono import StreamingResamplerTo16kMono
from engine.audio.timestamped_audio_ring_buffer import TimestampedAudioRingBuffer

__all__ = [
    "PIPELINE_SAMPLE_RATE",
    "AudioFrame",
    "CaptureBackend",
    "CaptureDeviceSpec",
    "CaptureStreamHandle",
    "DualStreamCaptureController",
    "StreamLabel",
    "StreamingResamplerTo16kMono",
    "TimestampedAudioRingBuffer",
]
