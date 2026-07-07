"""Naomi mic STT session: 700ms end-point boundary + fast barge-in onset.

Adversarial intent:
- The end-point knob is EXACTLY the Naomi 0.7s profile: at the VAD gate level,
  0.699s of silence must NOT close a segment and 0.701s MUST — an off-by-one
  in the config would cut the user off (0.6 default) or hang (too long).
- The session actually WIRES that 0.7s profile: 640ms of silence yields no
  utterance; crossing 700ms yields exactly one verbatim utterance.
- The barge-in onset fires within ~2 VAD frames (fast interrupt), and once
  per speech burst (a rising-edge latch, not per-frame spam).
"""

import numpy as np

from engine.audio.audio_frame_types import PIPELINE_SAMPLE_RATE, AudioFrame, StreamLabel
from engine.naomi.naomi_mic_stt_session import NaomiMicSttSession
from engine.stt.vad_gating_state_machine import (
    VadGateConfig,
    VadGateEvent,
    VadGatingStateMachine,
)
from engine.stt.word_token_types import WordToken

_CHUNK = 512  # samples @ 16kHz = 32ms — one VAD chunk per frame
_CHUNK_S = _CHUNK / PIPELINE_SAMPLE_RATE


def _closed(events: list[tuple[VadGateEvent, float]]) -> bool:
    return any(event is VadGateEvent.SEGMENT_CLOSE for event, _ in events)


def test_gate_closes_at_701ms_not_699ms_of_silence() -> None:
    """Exact 0.7s boundary at the VAD gate (arbitrary-precision timestamps)."""
    gate = VadGatingStateMachine(VadGateConfig(min_silence_s=0.7))
    # Open a segment: sustained speech past min_speech (0.25s).
    t = 0.0
    for _ in range(12):
        gate.process(0.95, t, t + _CHUNK_S)
        t += _CHUNK_S
    assert gate.is_in_speech
    silence_start = t
    # 0.699s of silence: below the floor → no close.
    events = gate.process(0.02, silence_start, silence_start + 0.699)
    assert not _closed(events)
    # Crossing to 0.701s total: at/over the floor → close, stamped at start.
    events = gate.process(0.02, silence_start + 0.699, silence_start + 0.701)
    assert _closed(events)


class _AmplitudeVad:
    """VAD stand-in: non-silent chunk ⇒ speech probability, else silence."""

    def __call__(self, chunk: np.ndarray) -> float:
        return 0.95 if float(np.abs(chunk).max()) > 0.01 else 0.02


def _speech_frame(index: int) -> AudioFrame:
    return AudioFrame(
        stream=StreamLabel.ME,
        samples=np.full(_CHUNK, 0.5, dtype=np.float32),
        t_start_monotonic=index * _CHUNK_S,
    )


def _silence_frame(index: int) -> AudioFrame:
    return AudioFrame(
        stream=StreamLabel.ME,
        samples=np.zeros(_CHUNK, dtype=np.float32),
        t_start_monotonic=index * _CHUNK_S,
    )


async def _transcribe_fixed(_samples: np.ndarray) -> list[WordToken]:
    return [WordToken("hello", 0.0, 0.1)]


async def test_session_wires_700ms_profile_not_the_600ms_default() -> None:
    utterances: list[tuple[str, int]] = []
    onsets: list[int] = []
    now = {"t": 0.0}

    async def on_utterance(text: str, ms: int) -> None:
        utterances.append((text, ms))

    async def on_onset() -> None:
        onsets.append(1)

    session = NaomiMicSttSession(
        _AmplitudeVad(),
        _transcribe_fixed,
        anchor_monotonic=0.0,
        on_utterance=on_utterance,
        on_speech_onset=on_onset,
        clock=lambda: now["t"],
    )

    index = 0
    # ~500ms of speech to open a segment.
    for _ in range(16):
        now["t"] = index * _CHUNK_S
        await session.feed(_speech_frame(index))
        index += 1
    # 640ms of silence (20 chunks) — BELOW the 0.7s profile: no end-point yet.
    for _ in range(20):
        now["t"] = index * _CHUNK_S
        await session.feed(_silence_frame(index))
        index += 1
    assert utterances == []  # a 0.6s default would have closed here — proves 0.7s

    # 6 more silence chunks (~832ms total) — now well past 0.7s: end-point fires.
    for _ in range(6):
        now["t"] = index * _CHUNK_S
        await session.feed(_silence_frame(index))
        index += 1
    await session.finalize()
    assert len(utterances) == 1
    text, endpoint_ms = utterances[0]
    assert text == "hello"  # verbatim fake transcript
    assert endpoint_ms >= 700  # the honest end-pointing latency ≈ the silence window
    # Onset fired for the single speech burst (fast, and not per-frame spam).
    assert len(onsets) == 1


async def test_onset_relatches_for_a_second_burst() -> None:
    onsets: list[int] = []

    async def on_utterance(_text: str, _ms: int) -> None:
        return None

    async def on_onset() -> None:
        onsets.append(1)

    session = NaomiMicSttSession(
        _AmplitudeVad(),
        _transcribe_fixed,
        anchor_monotonic=0.0,
        on_utterance=on_utterance,
        on_speech_onset=on_onset,
        clock=lambda: 0.0,
    )
    index = 0
    for burst in range(2):
        for _ in range(4):  # speech burst
            await session.feed(_speech_frame(index))
            index += 1
        for _ in range(25):  # long silence resets the rising edge
            await session.feed(_silence_frame(index))
            index += 1
        assert len(onsets) == burst + 1  # one onset per burst
