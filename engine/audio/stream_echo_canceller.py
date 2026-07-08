"""Thread-safe loopback buffer for simple echo cancellation on the mic stream."""

from __future__ import annotations

import threading
from collections import deque

import numpy as np

from engine.audio.echo_cancellation_processor import apply_echo_cancellation

# ~0.5 s of 16 kHz mono float32 loopback for AEC reference.
_MAX_REFERENCE_SAMPLES = 8_000


class StreamEchoCanceller:
    """Stores recent loopback (them) samples; cancels echo from mic (me) chunks."""

    def __init__(self, strength: float = 0.35) -> None:
        self._strength = strength
        self._lock = threading.Lock()
        self._them_chunks: deque[np.ndarray] = deque()

    def feed_loopback(self, samples: np.ndarray) -> None:
        if samples.size == 0:
            return
        with self._lock:
            self._them_chunks.append(samples.astype(np.float32, copy=False))
            total = sum(chunk.size for chunk in self._them_chunks)
            while total > _MAX_REFERENCE_SAMPLES and self._them_chunks:
                dropped = self._them_chunks.popleft()
                total -= dropped.size

    def process_mic(self, samples: np.ndarray) -> np.ndarray:
        if samples.size == 0:
            return samples
        with self._lock:
            if not self._them_chunks:
                return samples
            loopback = np.concatenate(list(self._them_chunks))
        return apply_echo_cancellation(samples, loopback, strength=self._strength)
