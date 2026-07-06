"""Typed contracts for transcribed words and windows.

Purpose: the data shapes exchanged between the transcriber (produces
window-local word timestamps) and the streaming chunk merger (stitches
windows into one word sequence). Frozen dataclasses so tokens are
immutable by construction — a merged token is provably the SAME token the
model emitted.
Pipeline position: between ``engine.stt.parakeet_nemo_transcriber`` and
``engine.stt.streaming_chunk_merger``.

Fidelity invariant (binding): ``WordToken.text`` is never rewritten after
creation; immutability makes accidental mutation impossible.
"""

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class WordToken:
    """One word as the model heard it, with absolute (stream) timestamps.

    ``t_start`` / ``t_end`` are seconds from meeting start. Frozen: the
    text IS the raw transcript — nothing downstream may alter it.
    """

    text: str
    t_start: float
    t_end: float

    def __post_init__(self) -> None:
        # Fail closed on garbage times: NaN/inf or inverted intervals would
        # silently corrupt merge ordering downstream.
        if not (math.isfinite(self.t_start) and math.isfinite(self.t_end)):
            raise ValueError(f"word {self.text!r} has non-finite timestamps")
        if self.t_end < self.t_start:
            raise ValueError(f"word {self.text!r} has t_end < t_start")

    @property
    def midpoint(self) -> float:
        """Temporal midpoint — the merge cut rule compares midpoints."""
        return (self.t_start + self.t_end) / 2.0


@dataclass(frozen=True)
class TranscribedWindow:
    """The transcription of one audio window, in absolute stream time.

    ``index`` is the window's position within its speech segment (0-based,
    hop-ordered); the merger uses it to process windows in order even when
    transcriptions finish out of order.
    """

    index: int
    t_start: float
    t_end: float
    words: tuple[WordToken, ...]

    def __post_init__(self) -> None:
        if not (math.isfinite(self.t_start) and math.isfinite(self.t_end)):
            raise ValueError(f"window {self.index} has non-finite bounds")
        if self.t_end < self.t_start:
            raise ValueError(f"window {self.index} has t_end < t_start")
        if self.index < 0:
            raise ValueError(f"window index must be >= 0, got {self.index}")
