"""Assembles gated speech audio into fixed overlapping transcription windows.

Purpose: turns the continuous audio of one open speech segment into the
chunked-streaming shape the transcriber consumes — 4.0 s windows advancing
by a 3.2 s hop (0.8 s overlap). All arithmetic is in integer SAMPLES, not
float seconds, so window boundaries are exact and drift-free over long
segments.
Pipeline position: between the VAD gate and the transcriber inside
``engine.stt.per_stream_transcription_pipeline``; its output windows feed
``engine.stt.streaming_chunk_merger``.

Security invariant: buffered audio is trimmed as soon as a window no
longer needs it and the segment buffer is dropped on ``close`` — audio is
held only as long as transcription requires it (discard-after-transcribe).
"""

from dataclasses import dataclass

import numpy as np
import numpy.typing as npt

from engine.audio.audio_frame_types import PIPELINE_SAMPLE_RATE

# Chunked-streaming geometry (pinned by the M1 design): 4 s of context per
# window, 0.8 s re-heard by the next window so the merger can stitch on
# word timestamps.
WINDOW_SECONDS = 4.0
HOP_SECONDS = 3.2

# A final tail shorter than this is not worth a model call: at 50 ms it
# cannot contain even one phoneme the previous window did not already hear.
_MIN_FINAL_WINDOW_SAMPLES = int(0.05 * PIPELINE_SAMPLE_RATE)


@dataclass(frozen=True)
class AssembledWindow:
    """One window of segment audio, in absolute stream time."""

    index: int
    t_start: float
    samples: npt.NDArray[np.float32]

    @property
    def t_end(self) -> float:
        """End time derived from exact sample count — no drift."""
        return self.t_start + len(self.samples) / PIPELINE_SAMPLE_RATE


class StreamingWindowAssembler:
    """Per-segment window cutter. ``open`` -> ``feed``* -> ``close``."""

    def __init__(
        self, window_s: float = WINDOW_SECONDS, hop_s: float = HOP_SECONDS
    ) -> None:
        if not 0 < hop_s <= window_s:
            raise ValueError(f"need 0 < hop ({hop_s}) <= window ({window_s})")
        self._window_samples = round(window_s * PIPELINE_SAMPLE_RATE)
        self._hop_samples = round(hop_s * PIPELINE_SAMPLE_RATE)
        self._open = False
        self._t_open_s = 0.0
        self._chunks: list[npt.NDArray[np.float32]] = []
        self._buffer_start_offset = 0  # Absolute sample offset of _chunks[0][0].
        self._total_samples = 0  # Absolute sample count fed so far.
        self._next_window_index = 0

    @property
    def is_open(self) -> bool:
        return self._open

    def open(self, t_open_s: float) -> None:
        """Start a new segment whose first sample is at ``t_open_s``."""
        if self._open:
            raise RuntimeError("assembler already has an open segment")
        self._open = True
        self._t_open_s = t_open_s
        self._chunks = []
        self._buffer_start_offset = 0
        self._total_samples = 0
        self._next_window_index = 0

    def feed(self, samples: npt.NDArray[np.float32]) -> list[AssembledWindow]:
        """Append segment audio; return any full windows now complete."""
        if not self._open:
            raise RuntimeError("feed() called with no open segment")
        if samples.size:
            self._chunks.append(samples)
            self._total_samples += samples.size
        emitted: list[AssembledWindow] = []
        while True:
            start = self._next_window_index * self._hop_samples
            end = start + self._window_samples
            if self._total_samples < end:
                break
            emitted.append(self._cut_window(start, end))
            self._next_window_index += 1
            self._trim_consumed_prefix()
        return emitted

    def close(self) -> AssembledWindow | None:
        """End the segment; return the final partial window, if any.

        The tail window covers audio from the next hop position to the end
        of the segment — audio no full window has fully "owned" yet. A
        sub-50 ms tail is skipped (nothing new to hear). The buffer is
        dropped either way (audio-discarded invariant).
        """
        if not self._open:
            raise RuntimeError("close() called with no open segment")
        start = self._next_window_index * self._hop_samples
        tail: AssembledWindow | None = None
        if self._total_samples - start >= max(1, _MIN_FINAL_WINDOW_SAMPLES):
            tail = self._cut_window(start, self._total_samples)
        self._open = False
        self._chunks = []  # Discard-after-transcribe: nothing outlives the segment.
        return tail

    def _cut_window(self, start: int, end: int) -> AssembledWindow:
        """Materialise absolute sample range [start, end) as one window."""
        joined = np.concatenate(self._chunks) if self._chunks else np.zeros(0, dtype=np.float32)
        lo = start - self._buffer_start_offset
        hi = end - self._buffer_start_offset
        window = AssembledWindow(
            index=self._next_window_index,
            t_start=self._t_open_s + start / PIPELINE_SAMPLE_RATE,
            samples=joined[lo:hi].copy(),
        )
        # Re-pack the buffer as one chunk so repeated concatenation stays cheap.
        self._chunks = [joined]
        return window

    def _trim_consumed_prefix(self) -> None:
        """Drop buffered audio no future window can need (memory bound)."""
        keep_from = self._next_window_index * self._hop_samples
        drop = keep_from - self._buffer_start_offset
        if drop <= 0 or not self._chunks:
            return
        joined = np.concatenate(self._chunks)
        self._chunks = [joined[drop:]]
        self._buffer_start_offset = keep_from
