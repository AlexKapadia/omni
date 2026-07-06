"""Pure VAD gating state machine: speech probabilities -> segment events.

Purpose: turns per-chunk speech probabilities (from Silero VAD) into
clean SEGMENT_OPEN / SEGMENT_CLOSE events with hysteresis and minimum
durations, so the transcriber only ever sees confirmed speech and short
blips/pauses do not fragment segments.

State model (documented contract):
- IDLE --(p >= enter)--> PENDING_SPEECH (candidate start remembered)
- PENDING_SPEECH --(p < exit)--> IDLE (false trigger, nothing emitted)
- PENDING_SPEECH --(speech run >= min_speech)--> SPEAKING, emits
  SEGMENT_OPEN stamped at the CANDIDATE start (retroactive: the first
  syllables belong to the segment).
- SPEAKING --(p < exit)--> PENDING_SILENCE (silence start remembered)
- PENDING_SILENCE --(p >= enter)--> SPEAKING (pause, not an ending)
- PENDING_SILENCE --(silence run >= min_silence)--> IDLE, emits
  SEGMENT_CLOSE stamped at the SILENCE start (where the speech ended —
  the hangover wait is not billed to the segment).

Hysteresis (enter > exit) prevents flutter around a single threshold.
Boundary semantics are exact: a run EQUAL to the minimum duration counts
(>=), pinned by tests.

Pipeline position: between the Silero ONNX detector and the window
assembler inside ``engine.stt.per_stream_transcription_pipeline``.

Fail-closed invariant: a probability outside [0, 1] (including NaN)
raises immediately — garbage confidence must never silently gate audio.
"""

import math
from dataclasses import dataclass
from enum import Enum


class VadGateEvent(Enum):
    """Emitted transitions, each paired with its stream-time in seconds."""

    SEGMENT_OPEN = "segment_open"
    SEGMENT_CLOSE = "segment_close"


class _State(Enum):
    IDLE = "idle"
    PENDING_SPEECH = "pending_speech"
    SPEAKING = "speaking"
    PENDING_SILENCE = "pending_silence"


@dataclass(frozen=True)
class VadGateConfig:
    """Tuning knobs, defaulted to Silero's recommended operating point.

    ``exit_threshold`` sits 0.15 below ``enter_threshold`` per the Silero
    authors' guidance (negative threshold = threshold - 0.15).
    """

    enter_threshold: float = 0.5
    exit_threshold: float = 0.35
    min_speech_s: float = 0.25
    min_silence_s: float = 0.6

    def __post_init__(self) -> None:
        if not (0.0 < self.exit_threshold <= self.enter_threshold <= 1.0):
            raise ValueError("thresholds must satisfy 0 < exit <= enter <= 1")
        if self.min_speech_s < 0 or self.min_silence_s < 0:
            raise ValueError("minimum durations must be >= 0")


class VadGatingStateMachine:
    """Feed (probability, chunk times) in stream order; collect gate events."""

    def __init__(self, config: VadGateConfig | None = None) -> None:
        self._config = config or VadGateConfig()
        self._state = _State.IDLE
        self._candidate_start_s = 0.0  # Start of the current speech candidate.
        self._silence_start_s = 0.0  # Start of the current silence candidate.

    @property
    def is_in_speech(self) -> bool:
        """True while audio should flow to the transcriber (open segment)."""
        return self._state in (_State.SPEAKING, _State.PENDING_SILENCE)

    def process(
        self, probability: float, chunk_start_s: float, chunk_end_s: float
    ) -> list[tuple[VadGateEvent, float]]:
        """Advance the machine by one VAD chunk; return emitted events.

        ``chunk_start_s`` / ``chunk_end_s`` are stream-time bounds of the
        audio the probability describes. At most one event per call.
        """
        # Fail closed: NaN fails both comparisons below, so check explicitly.
        if not (math.isfinite(probability) and 0.0 <= probability <= 1.0):
            raise ValueError(f"VAD probability must be in [0, 1], got {probability!r}")
        cfg = self._config

        if self._state is _State.IDLE:
            if probability >= cfg.enter_threshold:
                self._candidate_start_s = chunk_start_s
                self._state = _State.PENDING_SPEECH
                # Degenerate config min_speech_s == 0: confirm immediately.
                return self._maybe_confirm_speech(chunk_end_s)
            return []

        if self._state is _State.PENDING_SPEECH:
            if probability < cfg.exit_threshold:
                self._state = _State.IDLE  # False trigger — never opened.
                return []
            return self._maybe_confirm_speech(chunk_end_s)

        if self._state is _State.SPEAKING:
            if probability < cfg.exit_threshold:
                self._silence_start_s = chunk_start_s
                self._state = _State.PENDING_SILENCE
                return self._maybe_confirm_silence(chunk_end_s)
            return []

        # PENDING_SILENCE.
        if probability >= cfg.enter_threshold:
            self._state = _State.SPEAKING  # Just a pause; segment continues.
            return []
        return self._maybe_confirm_silence(chunk_end_s)

    def _maybe_confirm_speech(self, chunk_end_s: float) -> list[tuple[VadGateEvent, float]]:
        """PENDING_SPEECH -> SPEAKING when the run reaches min_speech (>=)."""
        if chunk_end_s - self._candidate_start_s >= self._config.min_speech_s:
            self._state = _State.SPEAKING
            # Retroactive stamp: the segment starts where speech STARTED.
            return [(VadGateEvent.SEGMENT_OPEN, self._candidate_start_s)]
        return []

    def _maybe_confirm_silence(self, chunk_end_s: float) -> list[tuple[VadGateEvent, float]]:
        """PENDING_SILENCE -> IDLE when the run reaches min_silence (>=)."""
        if chunk_end_s - self._silence_start_s >= self._config.min_silence_s:
            self._state = _State.IDLE
            # Stamp at silence start: that is where the speech actually ended.
            return [(VadGateEvent.SEGMENT_CLOSE, self._silence_start_s)]
        return []

    def force_close(self, at_s: float) -> list[tuple[VadGateEvent, float]]:
        """Close any open segment immediately (capture stopping).

        Emits SEGMENT_CLOSE if a segment was open (confirmed speech);
        pending-but-unconfirmed speech is discarded, matching the normal
        min-duration rule.
        """
        was_open = self.is_in_speech
        self._state = _State.IDLE
        if was_open:
            return [(VadGateEvent.SEGMENT_CLOSE, at_s)]
        return []
