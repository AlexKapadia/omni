"""Mic-only STT session for the Naomi loop: frames → VAD → verbatim utterance.

Purpose: composes ``engine.stt`` into a MIC-ONLY transcription session that
end-points on ~700ms of silence and emits ONE verbatim utterance per turn,
while surfacing a fast speech-ONSET signal for barge-in. It owns its own VAD
gate and window pipeline (its own instances — never shared with the meeting
loopback path), so Naomi listens to the user's mic and nothing else.
Pipeline position: owned by ``engine.naomi.naomi_turn_orchestrator``; fed
``AudioFrame``s by the mic backend (or, in the live test, by a PCM injector
at the ``feed`` seam — audio never has to be real hardware to exercise it).

Two signals, two latencies:
- END-POINT → verbatim utterance: the 700ms-silence VAD gate closes a
  segment; the Parakeet words are joined verbatim (fidelity mandate — the
  raw transcript is ground truth, never reworded) and handed up with the
  measured end-pointing latency.
- ONSET → barge-in: an independent 2-frame rising-edge detector on the SAME
  VAD probabilities fires ~64ms after speech starts — deliberately FASTER
  than the gate's 250ms speech-confirm — so the orchestrator can silence
  Naomi the instant the user talks over her (brief §7 barge-in protocol).

Security / fidelity invariants:
- Audio flows through VAD/transcription and is discarded after (the pipeline
  owns that); this session holds no audio buffers of its own.
- Word text passes through verbatim; only a single-space join is applied.
"""

from collections.abc import Awaitable, Callable

import numpy as np
import numpy.typing as npt

from engine.audio.audio_frame_types import AudioFrame, StreamLabel
from engine.naomi.naomi_turn_latency_breakdown import milliseconds_between
from engine.stt.per_stream_transcription_pipeline import PerStreamTranscriptionPipeline
from engine.stt.vad_gating_state_machine import VadGateConfig, VadGatingStateMachine
from engine.stt.word_token_types import WordToken

# Naomi end-pointing profile: 700ms of sub-exit silence closes a turn. Longer
# than the meeting default (0.6s) so Naomi does not cut the user off mid-clause
# (false-positive discipline: prefer a slightly longer pause over truncation).
NAOMI_MIN_SILENCE_S = 0.7

# Barge-in onset: two consecutive VAD chunks (~64ms at 32ms/chunk) above the
# speech-enter threshold constitute an onset. Fewer frames would false-trigger
# on transients; more would slow the interrupt below the brief's ~60ms target.
_ONSET_CONSECUTIVE_FRAMES = 2

UtteranceCallback = Callable[[str, int], Awaitable[None]]  # (verbatim_text, endpoint_ms)
OnsetCallback = Callable[[], Awaitable[None]]
PartialCallback = Callable[[str], Awaitable[None]]
VadProbabilityFn = Callable[[npt.NDArray[np.float32]], float]
TranscribeFn = Callable[[npt.NDArray[np.float32]], Awaitable[list[WordToken]]]


def words_to_verbatim_utterance(words: list[WordToken]) -> str:
    """Join transcribed words into the verbatim utterance (single space).

    Mirrors the dictation fidelity rule: the ONLY assembly step is a
    single-space join — no rewriting, no punctuation invention, no filler
    removal (that is an enhancement-layer concern, never the raw transcript).
    """
    return " ".join(word.text for word in words)


class NaomiMicSttSession:
    """One mic listening session: feed frames, get onsets and utterances."""

    def __init__(
        self,
        vad_probability: VadProbabilityFn,
        transcribe: TranscribeFn,
        *,
        anchor_monotonic: float,
        on_utterance: UtteranceCallback,
        on_speech_onset: OnsetCallback | None = None,
        on_partial: PartialCallback | None = None,
        clock: Callable[[], float],
        min_silence_s: float = NAOMI_MIN_SILENCE_S,
    ) -> None:
        self._silero = vad_probability
        self._on_utterance = on_utterance
        self._on_speech_onset = on_speech_onset
        self._on_partial = on_partial
        self._clock = clock
        self._anchor = anchor_monotonic
        # Build the gate config ONCE and read the onset thresholds straight
        # from it — the onset detector and the gate share the exact operating
        # point, so a barge-in can never disagree with an end-point.
        config = VadGateConfig(min_silence_s=min_silence_s)
        self._enter_threshold = config.enter_threshold
        self._exit_threshold = config.exit_threshold
        self._pipeline = PerStreamTranscriptionPipeline(
            stream=StreamLabel.ME,  # the USER's mic — never loopback
            anchor_monotonic=anchor_monotonic,
            vad_probability=self._probability_tap,
            transcribe=transcribe,
            on_partial=self._handle_partial,
            on_final=self._handle_final,
            gate=VadGatingStateMachine(config),
        )
        # Onset latch state (barge-in): consecutive above-enter frames, and a
        # latch so onset fires once per rising edge, not every speech chunk.
        self._consecutive_speech = 0
        self._onset_latched = False
        self._pending_onset = False

    async def feed(self, frame: AudioFrame) -> None:
        """Consume one mic frame; may fire onset (this call) and utterance."""
        await self._pipeline.feed(frame)
        # Onset is detected synchronously inside the pipeline's VAD tap; drain
        # it here where we can await, keeping the interrupt latency to ~1 frame.
        if self._pending_onset:
            self._pending_onset = False
            if self._on_speech_onset is not None:
                await self._on_speech_onset()

    async def finalize(self) -> None:
        """Close any open segment and await transcription (turn/session end)."""
        await self._pipeline.finalize()

    def _probability_tap(self, chunk: npt.NDArray[np.float32]) -> float:
        """Compute the VAD probability AND run the barge-in onset detector.

        The pipeline calls this per 512-sample chunk; we tap it so onset
        detection shares the exact same probabilities as end-pointing (one
        VAD evaluation, two consumers) — no second model, no drift.
        """
        probability = self._silero(chunk)
        if probability >= self._enter_threshold:
            self._consecutive_speech += 1
            if self._consecutive_speech >= _ONSET_CONSECUTIVE_FRAMES and not self._onset_latched:
                self._onset_latched = True
                self._pending_onset = True  # awaited by feed() after this returns
        elif probability < self._exit_threshold:
            # Sustained silence: reset the rising edge so the NEXT utterance
            # can fire onset again (one onset per speech burst).
            self._consecutive_speech = 0
            self._onset_latched = False
        return probability

    async def _handle_final(
        self,
        words: list[WordToken],
        _t_open: float,
        t_close: float,
        _segment_audio: object = None,
    ) -> None:
        """A segment closed: emit the verbatim utterance + end-point latency."""
        text = words_to_verbatim_utterance(words)
        if not text:
            return  # VAD fired but nothing was heard — no turn to answer
        # End-pointing latency: from the moment speech stopped (t_close, in
        # meeting-relative seconds off the anchor) to now (segment finalized).
        endpoint_ms = milliseconds_between(self._anchor + t_close, self._clock())
        await self._on_utterance(text, endpoint_ms)

    async def _handle_partial(self, words: list[WordToken]) -> None:
        if self._on_partial is not None:
            await self._on_partial(words_to_verbatim_utterance(words))
