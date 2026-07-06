"""Ad-hoc call suspicion from sustained speech on the render (loopback) device.

Purpose: catch calls that no process/window/registry signature covers (an
unknown app, a phone call routed through the PC) by noticing SUSTAINED
speech coming out of the speakers while no capture is running.

Interface-only here: the samples are ``(timestamp_s, speech_probability)``
pairs that the wiring pass will feed from the EXISTING loopback Silero VAD
(``engine.stt.silero_onnx_voice_activity_detector`` output on the loopback
stream) via ``DetectionService.feed_vad_sample``. This module performs no
audio I/O of its own.

Mechanism (documented contract):
- Each sample classifies as speech when ``probability >= speech_prob_threshold``.
- A sample accounts for the audio time since the PREVIOUS sample, capped at
  ``max_sample_gap_s`` — a feed gap means "nothing was measured", and unmeasured
  time must never be billed as speech (fail closed).
- Fire when speech time inside the rolling window reaches
  ``min_speech_s_in_window`` (boundary-exact: equal counts, ``>=``).
- Hysteresis + cooldown so it never spams: after firing, it re-arms only
  once BOTH the cooldown has elapsed AND speech in the window has drained
  below ``rearm_below_speech_s`` (i.e. the suspected call actually ended).
- ``capture_active=True`` keeps it silent (the meeting is already being
  captured); state still updates so nothing misfires when capture stops.

Security/compliance invariants:
- Consumes only speech PROBABILITIES — no audio, no transcript content, so
  nothing here can leak what was said.
- Fail closed on garbage: NaN / out-of-range probabilities and
  non-monotonic timestamps raise immediately rather than silently driving
  a capture suggestion.
"""

from collections import deque
from dataclasses import dataclass
from enum import Enum
from math import isnan

from engine.detect.detection_signal_types import SOURCE_ADHOC_LOOPBACK, AdHocCallSuspected

# Confidence assigned to an ad-hoc suspicion: real sustained speech, but no
# app-level evidence of a *meeting* — enough to suggest, never to auto-start.
_ADHOC_CONFIDENCE = 0.7


@dataclass(frozen=True)
class SustainedLoopbackVadConfig:
    """Tuning knobs. Defaults: ~12s of speech inside a 30s window fires."""

    speech_prob_threshold: float = 0.5
    rolling_window_s: float = 30.0
    min_speech_s_in_window: float = 12.0
    rearm_below_speech_s: float = 4.0
    cooldown_s: float = 120.0
    max_sample_gap_s: float = 1.0

    def __post_init__(self) -> None:
        if not (0.0 < self.speech_prob_threshold < 1.0):
            raise ValueError("speech_prob_threshold must be in (0, 1)")
        if self.rolling_window_s <= 0 or self.max_sample_gap_s <= 0:
            raise ValueError("rolling_window_s and max_sample_gap_s must be > 0")
        if not (0.0 < self.min_speech_s_in_window <= self.rolling_window_s):
            raise ValueError("min_speech_s_in_window must be in (0, rolling_window_s]")
        if not (0.0 <= self.rearm_below_speech_s < self.min_speech_s_in_window):
            # WHY: re-arm level must sit BELOW the fire level or hysteresis
            # degenerates and one long call re-fires every cooldown period.
            raise ValueError("rearm_below_speech_s must be in [0, min_speech_s_in_window)")
        if self.cooldown_s < 0:
            raise ValueError("cooldown_s must be >= 0")


class _TriggerState(Enum):
    ARMED = "armed"
    COOLDOWN = "cooldown"


class SustainedLoopbackVadTrigger:
    """Feed loopback-VAD samples in stream order; get at most rare events."""

    def __init__(self, config: SustainedLoopbackVadConfig | None = None) -> None:
        self._config = config or SustainedLoopbackVadConfig()
        # Entries: (sample_ts_s, accounted_duration_s, is_speech).
        self._samples: deque[tuple[float, float, bool]] = deque()
        self._speech_seconds = 0.0  # running sum over the deque (exact bookkeeping)
        self._last_sample_ts: float | None = None
        self._state = _TriggerState.ARMED
        self._fired_at_ts = 0.0

    @property
    def speech_seconds_in_window(self) -> float:
        """Current accounted speech time inside the rolling window."""
        return self._speech_seconds

    def reset(self) -> None:
        """Drop all rolling state (e.g. on audio-device change)."""
        self._samples.clear()
        self._speech_seconds = 0.0
        self._last_sample_ts = None
        self._state = _TriggerState.ARMED

    def feed(
        self,
        sample_ts_s: float,
        speech_probability: float,
        capture_active: bool,
    ) -> AdHocCallSuspected | None:
        """Ingest one loopback-VAD sample; return an event iff it fires now."""
        # Fail closed: garbage confidence must never gate a capture decision.
        if isnan(speech_probability) or not (0.0 <= speech_probability <= 1.0):
            raise ValueError(f"speech_probability must be in [0, 1], got {speech_probability!r}")
        if isnan(sample_ts_s):
            raise ValueError("sample_ts_s must not be NaN")
        if self._last_sample_ts is not None and sample_ts_s < self._last_sample_ts:
            raise ValueError(
                f"samples must arrive in stream order: {sample_ts_s} < {self._last_sample_ts}"
            )

        is_speech = speech_probability >= self._config.speech_prob_threshold
        # First sample carries no elapsed audio; later samples account the
        # time since the previous sample, capped so feed gaps (paused stream,
        # device swap) are never billed as speech.
        if self._last_sample_ts is None:
            duration = 0.0
        else:
            duration = min(sample_ts_s - self._last_sample_ts, self._config.max_sample_gap_s)
        self._last_sample_ts = sample_ts_s

        self._samples.append((sample_ts_s, duration, is_speech))
        if is_speech:
            self._speech_seconds += duration
        self._evict_outside_window(sample_ts_s)

        if self._state is _TriggerState.COOLDOWN:
            cooldown_over = sample_ts_s - self._fired_at_ts >= self._config.cooldown_s
            drained = self._speech_seconds <= self._config.rearm_below_speech_s
            if cooldown_over and drained:
                self._state = _TriggerState.ARMED
            return None  # hysteresis: never fire while cooling down

        if capture_active:
            return None  # already capturing: quiet by contract
        if self._speech_seconds >= self._config.min_speech_s_in_window:
            self._state = _TriggerState.COOLDOWN
            self._fired_at_ts = sample_ts_s
            return AdHocCallSuspected(
                source=SOURCE_ADHOC_LOOPBACK,
                speech_seconds_in_window=self._speech_seconds,
                rolling_window_s=self._config.rolling_window_s,
                confidence=_ADHOC_CONFIDENCE,
            )
        return None

    def _evict_outside_window(self, now_ts_s: float) -> None:
        """Drop samples whose timestamp fell out of the rolling window."""
        cutoff = now_ts_s - self._config.rolling_window_s
        while self._samples and self._samples[0][0] <= cutoff:
            _, duration, was_speech = self._samples.popleft()
            if was_speech:
                self._speech_seconds -= duration
        # Guard against float drift ever producing a negative sum.
        self._speech_seconds = max(self._speech_seconds, 0.0)
