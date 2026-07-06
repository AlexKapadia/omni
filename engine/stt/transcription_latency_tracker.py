"""Latency instrumentation for transcript finalisation (speed showcase).

Purpose: records the audio-end -> emit lag of every ``transcript.final``
and reports p50/p95 to the engine log every 60 s while capture runs —
real-time performance is a user-facing showcase feature, so it is
measured, not assumed.
Pipeline position: owned by ``engine.stt.live_capture_service``; fed by
final-event emission, drained by the periodic stats task.

No security surface: only durations are recorded — never text, audio, or
device identifiers.
"""

import logging
import math
from collections import deque

logger = logging.getLogger(__name__)

# Rolling window: enough finals for stable percentiles, bounded memory.
_MAX_RECORDED_LAGS = 512

# Log cadence pinned by the M1 instrumentation mandate.
STATS_LOG_INTERVAL_S = 60.0


class TranscriptionLatencyTracker:
    """Rolling lag_ms window with exact nearest-rank percentiles."""

    def __init__(self) -> None:
        self._lags_ms: deque[float] = deque(maxlen=_MAX_RECORDED_LAGS)
        self._recorded_total = 0

    def record(self, lag_ms: float) -> None:
        """Record one final's lag. Non-finite/negative values are rejected
        loudly — a broken clock must not silently poison the showcase numbers."""
        if not math.isfinite(lag_ms) or lag_ms < 0:
            raise ValueError(f"lag_ms must be finite and >= 0, got {lag_ms!r}")
        self._lags_ms.append(lag_ms)
        self._recorded_total += 1

    def percentile_ms(self, percentile: float) -> float | None:
        """Nearest-rank percentile over the rolling window; None when empty.

        Nearest-rank (not interpolated): every reported number is a REAL
        observed lag, defensible to the unit (zero-numerical-error rule).
        """
        if not 0 < percentile <= 100:
            raise ValueError(f"percentile must be in (0, 100], got {percentile}")
        if not self._lags_ms:
            return None
        ordered = sorted(self._lags_ms)
        rank = max(1, math.ceil(percentile / 100.0 * len(ordered)))
        return ordered[rank - 1]

    @property
    def recorded_total(self) -> int:
        """Finals recorded since capture start (not just the window)."""
        return self._recorded_total

    def log_summary(self) -> None:
        """Emit the p50/p95 line the 60 s stats task calls for."""
        p50 = self.percentile_ms(50)
        p95 = self.percentile_ms(95)
        if p50 is None or p95 is None:
            logger.info("stt latency: no finals emitted yet")
            return
        logger.info(
            "stt latency over last %d finals (%d total): p50=%.0f ms p95=%.0f ms",
            len(self._lags_ms),
            self._recorded_total,
            p50,
            p95,
        )
