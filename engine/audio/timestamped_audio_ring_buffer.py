"""Bounded, thread-safe ring buffer of timestamped audio frames.

Purpose: the hand-off point between PortAudio callback threads (producers)
and the asyncio STT pipeline (consumer). Bounded by total buffered seconds
with a drop-OLDEST policy so a stalled consumer can never grow memory
without limit — the freshest audio always wins.
Pipeline position: between ``engine.audio.dual_stream_capture_controller``
(writes from callback threads) and ``engine.stt``'s drain loop (reads from
the event loop).

Security invariant: this buffer is the ONLY place captured audio lives.
``drain()`` hands ownership to the transcription layer, which discards the
samples after transcribing them — audio is never written to disk and never
leaves the process (local-only invariant; keep-audio is a later opt-in).
"""

import threading
from collections import deque

from engine.audio.audio_frame_types import AudioFrame


class TimestampedAudioRingBuffer:
    """FIFO of ``AudioFrame``s bounded by total duration, drop-oldest.

    Thread-safe: producers are PortAudio callback threads, the consumer is
    the asyncio drain task. All operations are O(1) amortised and never
    block for long — the lock only guards deque bookkeeping (a callback
    thread must never stall the audio driver).
    """

    def __init__(self, max_buffered_seconds: float = 60.0) -> None:
        if max_buffered_seconds <= 0:
            raise ValueError(f"max_buffered_seconds must be positive, got {max_buffered_seconds}")
        self._max_buffered_seconds = max_buffered_seconds
        self._frames: deque[AudioFrame] = deque()
        self._buffered_seconds = 0.0
        self._dropped_seconds_total = 0.0
        self._lock = threading.Lock()

    def append(self, frame: AudioFrame) -> None:
        """Add a frame; evict oldest frames if the duration cap is exceeded.

        Drop-oldest (not drop-newest): if the consumer stalls, the most
        recent audio is the most valuable for a LIVE transcript — stale
        audio would only be transcribed late and mislabel the timeline.
        """
        with self._lock:
            self._frames.append(frame)
            self._buffered_seconds += frame.duration_s
            while self._buffered_seconds > self._max_buffered_seconds and len(self._frames) > 1:
                evicted = self._frames.popleft()
                self._buffered_seconds -= evicted.duration_s
                self._dropped_seconds_total += evicted.duration_s

    def drain(self) -> list[AudioFrame]:
        """Remove and return ALL buffered frames, oldest first.

        The returned frames are the sole remaining references to that
        audio; once the STT layer finishes with them they are garbage
        (audio-discarded-after-transcription invariant).
        """
        with self._lock:
            drained = list(self._frames)
            self._frames.clear()
            self._buffered_seconds = 0.0
        return drained

    @property
    def dropped_seconds_total(self) -> float:
        """Total seconds ever evicted — surfaced in logs, never silently lost."""
        with self._lock:
            return self._dropped_seconds_total

    @property
    def buffered_seconds(self) -> float:
        """Seconds currently held (diagnostics / backpressure visibility)."""
        with self._lock:
            return self._buffered_seconds
