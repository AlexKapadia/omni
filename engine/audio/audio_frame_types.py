"""Typed contracts for audio frames flowing from capture to transcription.

Purpose: the single definition of what a captured audio frame looks like
after normalisation — 16 kHz mono float32 samples labelled with which
stream they came from and WHEN they started on the shared monotonic clock.
Pipeline position: produced by ``engine.audio.dual_stream_capture_controller``,
buffered by ``engine.audio.timestamped_audio_ring_buffer``, consumed by
``engine.stt``.

Security invariant: frames are in-memory only. Nothing in this module (or
its consumers) persists raw audio — buffers are discarded once transcribed
(local-only invariant; keep-audio arrives later as an explicit opt-in).
"""

from dataclasses import dataclass
from enum import StrEnum

import numpy as np
import numpy.typing as npt

# Everything downstream of capture speaks 16 kHz mono float32 — the native
# input format of both Silero VAD and Parakeet-TDT. Resampling happens once,
# at the capture boundary, never again.
PIPELINE_SAMPLE_RATE = 16_000


class StreamLabel(StrEnum):
    """Which side of the conversation a frame belongs to.

    Values are pinned by the DB schema (``transcript_segments.stream``
    CHECK constraint) and the WS protocol — do not rename.
    """

    ME = "me"  # Default microphone: the user speaking.
    THEM = "them"  # WASAPI loopback of the default render device: everyone else.


@dataclass(frozen=True)
class AudioFrame:
    """One contiguous run of normalised audio from a single stream.

    ``samples``: float32 mono at ``PIPELINE_SAMPLE_RATE``, in [-1, 1].
    ``t_start_monotonic``: ``time.monotonic()`` reading for the FIRST sample
    — monotonic (not wall) time so ordering survives clock changes, and so
    device-change gaps show up honestly as missing time, never stretched
    audio.
    """

    stream: StreamLabel
    samples: npt.NDArray[np.float32]
    t_start_monotonic: float

    @property
    def duration_s(self) -> float:
        """Length of the frame in seconds at the pipeline sample rate."""
        return len(self.samples) / PIPELINE_SAMPLE_RATE

    @property
    def t_end_monotonic(self) -> float:
        """Monotonic time just after the LAST sample of the frame."""
        return self.t_start_monotonic + self.duration_s
