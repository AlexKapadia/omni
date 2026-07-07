"""Naomi mic capture source + turn orchestrator command/error edge branches.

Adversarial intent:
- The mic source opens the DEFAULT MIC (never loopback), resamples, and pumps
  frames to the sink; a malformed chunk is dropped (never crashes the audio
  callback), an empty chunk yields no frame, and stop() flushes the tail and
  is idempotent. A FAKE backend stands in for pyaudiowpatch — zero device I/O.
- The orchestrator's remaining command/error branches: a redundant listen.start
  is a no-op, a no-flush stop settles straight to idle, shutdown silences the
  speaker, an utterance while not listening is dropped, a turn-body exception
  becomes an honest error event, a late speaker-finished is ignored, and a
  speaker error while speaking fails the turn.
"""

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

import numpy as np
import numpy.typing as npt
import pytest

from engine.audio.audio_frame_types import PIPELINE_SAMPLE_RATE, AudioFrame, StreamLabel
from engine.audio.dual_stream_capture_controller import CaptureDeviceSpec
from engine.naomi import naomi_mic_capture_source as mic_source
from engine.naomi.naomi_action_intent_flow import NaomiActionResult
from engine.naomi.naomi_mic_capture_source import start_naomi_mic_capture
from engine.naomi.naomi_turn_orchestrator import NaomiTurnOrchestrator
from engine.naomi.naomi_turn_state_machine import NaomiTurnState
from engine.naomi.naomi_voice_answer_service import NaomiVoiceAnswer
from engine.protocol import EventBroadcastHub
from engine.protocol.websocket_envelope import Envelope
from engine.stt.word_token_types import WordToken

_CHUNK = 512
_CHUNK_S = _CHUNK / PIPELINE_SAMPLE_RATE


# --- Mic capture source ----------------------------------------------------


class FakeHandle:
    """A fake open stream handle: records closes, reports alive/dead."""

    def __init__(self) -> None:
        self.close_calls = 0

    def close(self) -> None:
        self.close_calls += 1

    @property
    def is_alive(self) -> bool:
        return self.close_calls == 0


class FakeMicBackend:
    """A fake capture backend: hands the on_chunk callback back to the test."""

    def __init__(self, *, sample_rate: int = PIPELINE_SAMPLE_RATE, channels: int = 1) -> None:
        self._spec = CaptureDeviceSpec(
            key="mic-1", name="Test Mic", sample_rate=sample_rate, channels=channels
        )
        self.probed: list[StreamLabel] = []
        self.on_chunk: Callable[[bytes, float], None] | None = None
        self.handle = FakeHandle()

    def probe_default_device(self, stream: StreamLabel) -> CaptureDeviceSpec:
        self.probed.append(stream)
        return self._spec

    def open_capture_stream(
        self, spec: CaptureDeviceSpec, on_chunk: Callable[[bytes, float], None]
    ) -> FakeHandle:
        self.on_chunk = on_chunk
        return self.handle


def _pcm16(values: list[int]) -> bytes:
    return np.array(values, dtype=np.int16).tobytes()


async def _collect_frames(sink_target: list[AudioFrame]) -> Callable[[AudioFrame], Awaitable[None]]:
    async def sink(frame: AudioFrame) -> None:
        sink_target.append(frame)

    return sink


async def test_mic_capture_pumps_labelled_resampled_frames_to_sink() -> None:
    """A raw int16 chunk becomes a ME-labelled 16k float32 frame at the sink."""
    frames: list[AudioFrame] = []
    sink = await _collect_frames(frames)
    backend = FakeMicBackend()

    stop = await start_naomi_mic_capture(sink, backend_factory=lambda: backend)
    assert backend.probed == [StreamLabel.ME]  # never loopback — Naomi hears the user
    assert backend.on_chunk is not None

    # int16 16384 → 0.5 in float32; 160 samples ending at t=1.0 start at 0.99.
    backend.on_chunk(_pcm16([16384] * 160), 1.0)
    await asyncio.sleep(0.08)  # let the ~50 ms drain pump run at least once
    await stop()

    assert len(frames) == 1
    frame = frames[0]
    assert frame.stream is StreamLabel.ME
    assert frame.samples.shape == (160,)
    assert frame.samples.dtype == np.float32
    assert float(frame.samples[0]) == pytest.approx(0.5)
    assert frame.t_start_monotonic == pytest.approx(1.0 - 160 / PIPELINE_SAMPLE_RATE)


async def test_mic_capture_drops_malformed_chunk_but_keeps_valid_ones() -> None:
    """A torn (odd-length) stereo chunk is dropped; the callback never raises."""
    frames: list[AudioFrame] = []
    sink = await _collect_frames(frames)
    backend = FakeMicBackend(channels=2)  # stereo → interleaved int16 pairs

    stop = await start_naomi_mic_capture(sink, backend_factory=lambda: backend)
    assert backend.on_chunk is not None

    # 3 int16 values is not divisible by 2 channels → resampler raises → dropped.
    backend.on_chunk(_pcm16([1, 2, 3]), 1.0)
    # A well-formed stereo pair (L=32768 clip→~1.0, R=0) → one mono sample = 0.5.
    backend.on_chunk(_pcm16([16384, 16384, 0, 0]), 2.0)
    await asyncio.sleep(0.08)
    await stop()

    # Only the valid chunk produced a frame; the malformed one vanished quietly.
    assert len(frames) == 1
    assert frames[0].samples.shape == (2,)
    assert float(frames[0].samples[0]) == pytest.approx(0.5)


async def test_mic_capture_empty_chunk_yields_no_frame() -> None:
    """A zero-sample chunk buffers nothing (no empty frames on the timeline)."""
    frames: list[AudioFrame] = []
    sink = await _collect_frames(frames)
    backend = FakeMicBackend()

    stop = await start_naomi_mic_capture(sink, backend_factory=lambda: backend)
    assert backend.on_chunk is not None
    backend.on_chunk(b"", 1.0)  # empty PCM → samples.size == 0 → skipped
    await asyncio.sleep(0.08)
    await stop()
    assert frames == []


async def test_mic_capture_stop_flushes_tail_and_is_idempotent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """stop() drains the un-pumped tail and can be called twice without error."""
    # Widen the drain cadence so the pump can NOT reach the tail — proving the
    # tail is flushed by stop() itself, not by an incidental pump tick.
    monkeypatch.setattr(mic_source, "_DRAIN_INTERVAL_S", 30.0)
    frames: list[AudioFrame] = []
    sink = await _collect_frames(frames)
    backend = FakeMicBackend()

    stop = await start_naomi_mic_capture(sink, backend_factory=lambda: backend)
    assert backend.on_chunk is not None
    await asyncio.sleep(0)  # let the drain task park on its (now 30 s) sleep
    # Append immediately, then stop: the tail must be flushed by stop(), never
    # dropped (the end of the utterance always reaches the sink).
    backend.on_chunk(_pcm16([16384] * 32), 0.5)
    await stop()
    assert len(frames) == 1  # flushed on stop, not by the pump
    assert backend.handle.close_calls >= 1

    await stop()  # idempotent: no new frames, no exception
    assert len(frames) == 1


# --- Orchestrator command/error edges --------------------------------------


class FakeAnswerService:
    async def answer(self, _utterance: str) -> NaomiVoiceAnswer:
        return NaomiVoiceAnswer(
            spoken_text="An answer.",
            affect=None,
            citations=(),
            no_answer=False,
            retrieval_ms=1,
            llm_ms=2,
        )


class RaisingAnswerService:
    async def answer(self, _utterance: str) -> NaomiVoiceAnswer:
        raise RuntimeError("kaboom in synthesis")


class NoActionFlow:
    async def maybe_prepare_action(self, _utterance: str) -> NaomiActionResult | None:
        return None


class FakeSpeaker:
    """Records speak/cancel/shutdown; holds 'speaking' until told to finish."""

    def __init__(self) -> None:
        self.speak_calls = 0
        self.cancels = 0
        self.shutdowns = 0
        self._on_finished: Callable[[str, str], Awaitable[None]] | None = None

    def set_finished_callback(self, cb: Callable[[str, str], Awaitable[None]]) -> None:
        self._on_finished = cb

    async def speak(
        self,
        chunks: object,
        affect: object,
        on_first_audio: Callable[[int], Awaitable[None]] | None = None,
    ) -> str:
        self.speak_calls += 1
        if on_first_audio is not None:
            await on_first_audio(30)
        return "ctx-fake"

    async def cancel(self) -> str:
        self.cancels += 1
        return "ctx-fake"

    async def finish(self, reason: str = "completed") -> None:
        assert self._on_finished is not None
        await self._on_finished("ctx-fake", reason)

    async def shutdown(self) -> None:
        self.shutdowns += 1


class _AmplitudeVad:
    def __call__(self, chunk: npt.NDArray[np.float32]) -> float:
        return 0.95 if float(np.abs(chunk).max()) > 0.01 else 0.02


async def _transcribe_fixed(_samples: npt.NDArray[np.float32]) -> list[WordToken]:
    return [WordToken("hello", 0.0, 0.1)]


class CountingCapture:
    """Counts start_capture invocations; returns a benign stop callback."""

    def __init__(self) -> None:
        self.starts = 0
        self.stops = 0

    async def __call__(
        self, _sink: Callable[[AudioFrame], Awaitable[None]]
    ) -> Callable[[], Awaitable[None]]:
        self.starts += 1

        async def stop() -> None:
            self.stops += 1

        return stop


class EventRecorder:
    def __init__(self, hub: EventBroadcastHub) -> None:
        self.events: list[tuple[str, dict[str, Any]]] = []
        hub.subscribe(self._send)

    async def _send(self, envelope: Envelope) -> None:
        self.events.append((envelope.name, dict(envelope.payload)))

    def names(self) -> list[str]:
        return [n for n, _ in self.events]


def _build(
    hub: EventBroadcastHub,
    speaker: FakeSpeaker,
    answer: object,
    *,
    start_capture: Callable[..., Any] | None = None,
) -> NaomiTurnOrchestrator:
    if start_capture is None:
        start_capture = CountingCapture()
    now = {"t": 0.0}
    orch = NaomiTurnOrchestrator(
        hub,
        answer,  # type: ignore[arg-type]
        NoActionFlow(),  # type: ignore[arg-type]
        speaker,  # type: ignore[arg-type]
        vad_factory=lambda: _AmplitudeVad(),
        transcribe=_transcribe_fixed,
        clock=lambda: now["t"],
        start_capture=start_capture,
    )
    speaker.set_finished_callback(orch.on_speaker_finished)
    return orch


def _frame(index: int, *, speech: bool) -> AudioFrame:
    fill = np.full(_CHUNK, 0.5, dtype=np.float32)
    samples = fill if speech else np.zeros(_CHUNK, dtype=np.float32)
    return AudioFrame(stream=StreamLabel.ME, samples=samples, t_start_monotonic=index * _CHUNK_S)


async def _await_state(orch: NaomiTurnOrchestrator, target: NaomiTurnState) -> None:
    for _ in range(500):
        if orch.state is target:
            return
        await asyncio.sleep(0)
    raise AssertionError(f"never reached {target} (stuck at {orch.state})")


async def test_redundant_listen_start_while_listening_is_a_noop() -> None:
    """A second listen.start while already listening opens no second capture."""
    hub = EventBroadcastHub()
    capture = CountingCapture()
    orch = _build(hub, FakeSpeaker(), FakeAnswerService(), start_capture=capture)

    await orch.listen_start(open_mic=True)
    assert orch.state is NaomiTurnState.LISTENING
    await orch.listen_start(open_mic=True)  # can_apply(START) is False → early out
    assert orch.state is NaomiTurnState.LISTENING
    assert capture.starts == 1  # exactly one capture session opened


async def test_listen_stop_without_flush_settles_straight_to_idle() -> None:
    """A discard (flush=False) stop closes capture and returns to idle at once."""
    hub = EventBroadcastHub()
    capture = CountingCapture()
    orch = _build(hub, FakeSpeaker(), FakeAnswerService(), start_capture=capture)

    await orch.listen_start(open_mic=False)
    await orch.listen_stop(flush=False)  # discard pending audio → STOP → idle
    assert orch.state is NaomiTurnState.IDLE
    assert capture.stops == 1  # capture was torn down


async def test_shutdown_silences_speaker_and_stops_capture() -> None:
    """Process shutdown closes capture, drops the session, silences the mouth."""
    hub = EventBroadcastHub()
    capture = CountingCapture()
    speaker = FakeSpeaker()
    orch = _build(hub, speaker, FakeAnswerService(), start_capture=capture)

    await orch.listen_start(open_mic=True)
    await orch.shutdown()
    assert speaker.shutdowns == 1  # the speaker/socket was silenced
    assert capture.stops == 1


async def test_utterance_while_not_listening_is_dropped() -> None:
    """The atomic guard: an utterance arriving in IDLE begins no turn."""
    hub = EventBroadcastHub()
    recorder = EventRecorder(hub)
    orch = _build(hub, FakeSpeaker(), FakeAnswerService())

    await orch._on_utterance("stray words", 100)  # state is IDLE, not LISTENING
    assert orch.state is NaomiTurnState.IDLE
    assert "naomi.user_utterance" not in recorder.names()  # nothing ran
    assert "naomi.reply" not in recorder.names()


async def test_turn_body_exception_becomes_honest_error_and_settles() -> None:
    """A synthesis failure surfaces as naomi.turn.error and settles the machine."""
    hub = EventBroadcastHub()
    recorder = EventRecorder(hub)
    orch = _build(hub, FakeSpeaker(), RaisingAnswerService())

    await orch.listen_start(open_mic=False)
    await orch._on_utterance("break it", 40)  # LISTENING → THINKING → raises

    errors = [p for n, p in recorder.events if n == "naomi.turn.error"]
    assert len(errors) == 1
    assert "kaboom in synthesis" in errors[0]["message"]
    assert orch.state is NaomiTurnState.IDLE  # failed turn settled (open_mic False)


async def test_late_speaker_finished_when_not_speaking_is_ignored() -> None:
    """A finished signal arriving after a barge-in already moved on is a no-op."""
    hub = EventBroadcastHub()
    orch = _build(hub, FakeSpeaker(), FakeAnswerService())

    await orch.listen_start(open_mic=True)
    assert orch.state is NaomiTurnState.LISTENING
    await orch.on_speaker_finished("ctx-late", "completed")  # not SPEAKING → ignore
    assert orch.state is NaomiTurnState.LISTENING  # unchanged


async def test_speaker_error_while_speaking_fails_the_turn() -> None:
    """A speaker 'error' completion drives the terminal FAIL transition."""
    hub = EventBroadcastHub()
    speaker = FakeSpeaker()
    orch = _build(hub, speaker, FakeAnswerService())

    await orch.listen_start(open_mic=True)  # resume→listening after a terminal
    index = 0
    for _ in range(16):  # ~500 ms of speech
        await orch.feed_audio_frame(_frame(index, speech=True))
        index += 1
    for _ in range(26):  # trailing silence end-points the utterance
        await orch.feed_audio_frame(_frame(index, speech=False))
        index += 1
    await _await_state(orch, NaomiTurnState.SPEAKING)

    await orch.on_speaker_finished("ctx-fake", "error")  # SPEAKING + error → FAIL
    # open_mic=True resumes to LISTENING for the next turn (never stuck SPEAKING).
    assert orch.state is NaomiTurnState.LISTENING
