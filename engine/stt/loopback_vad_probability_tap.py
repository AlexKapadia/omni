"""Loopback-VAD probability tap: the M6 detection feed, isolated.

Purpose: wraps a stream's VAD probability callable so every loopback
("them") speech probability is ALSO forwarded — timestamped — to the
detection wiring's ``feed_vad_sample``. Probabilities only, never audio;
this is the "no new audio path" seam the detection spec mandates.
Pipeline position: applied by ``engine.stt.live_capture_service`` when it
builds the THEM pipeline; consumed by ``engine.wiring.detection_server_wiring``.

Security / resilience invariants:
- Nothing but ``(monotonic_ts, probability)`` leaves the wrapper — no
  samples, no transcript content (local-only invariant).
- The tap is read at CALL time (the server attaches it after construction)
  and its failures are swallowed and logged: a detection bug must never
  break live transcription (fail closed, stay up).
"""

import logging
import time
from collections.abc import Callable

import numpy as np
import numpy.typing as npt

logger = logging.getLogger(__name__)

VadProbabilityFn = Callable[[npt.NDArray[np.float32]], float]
# (sample_ts_s, speech_probability) — matches DetectionService.feed_vad_sample.
LoopbackVadTap = Callable[[float, float], None]


def wrap_vad_with_loopback_tap(
    inner_vad: VadProbabilityFn, get_tap: Callable[[], LoopbackVadTap | None]
) -> VadProbabilityFn:
    """Return a VAD callable that also feeds the (late-bound) detection tap."""

    def vad_with_detection_tap(samples: npt.NDArray[np.float32]) -> float:
        probability = inner_vad(samples)
        tap = get_tap()
        if tap is not None:
            try:
                tap(time.monotonic(), probability)
            except Exception:
                logger.exception("loopback VAD tap failed; transcription continues")
        return probability

    return vad_with_detection_tap
