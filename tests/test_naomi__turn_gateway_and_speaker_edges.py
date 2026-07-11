"""Turn gateway lazy build/delegation + warm-socket speaker relay edges.

Adversarial intent:
- The gateway is INERT until first use: ``state`` reads IDLE and the
  delegating commands are no-ops before any orchestrator exists; the first
  build wires the real long-lived resources exactly once and re-wires the
  speaker's finished callback into the orchestrator.
- The speaker relays a Cartesia stream clause-by-clause over a FAKE warm
  connection (zero network): audio chunks carry the honest measured warm
  TTFA on seq 0 only, word timestamps and done are relayed on the SAME hub
  events, a provider/error frame becomes an honest ``error`` done, cancel is
  the barge-in wire (idempotent), and shutdown silences + closes the socket.

Every assertion pins an exact emitted event/payload or return value, so a
regression in the relay ordering, the TTFA arithmetic, or the cancel wiring
fails the test rather than passing silently.
"""

import asyncio
from collections.abc import Awaitable, Callable, Sequence
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from engine.audio.audio_frame_types import AudioFrame, StreamLabel
from engine.naomi import naomi_turn_gateway
from engine.naomi.naomi_turn_gateway import NaomiTurnGateway
from engine.naomi.naomi_turn_speaker import NaomiTurnSpeaker
from engine.naomi.naomi_turn_state_machine import NaomiTurnState
from engine.protocol import EventBroadcastHub
from engine.protocol.websocket_envelope import Envelope
from engine.voice.cartesia_message_framing import (
    CartesiaAudioChunk,
    CartesiaDone,
    CartesiaErrorMessage,
    CartesiaMessage,
    CartesiaWordTimestamps,
)
from engine.voice.voice_errors import VoiceEgressBlockedError, VoiceProviderError

_MIGRATIONS_DIR = Path(__file__).resolve().parents[1] / "migrations"


class EventRecorder:
    """Records (name, payload) for every broadcast event, in order."""

    def __init__(self, hub: EventBroadcastHub) -> None:
        self.events: list[tuple[str, dict[str, Any]]] = []
        hub.subscribe(self._send)

    async def _send(self, envelope: Envelope) -> None:
        self.events.append((envelope.name, dict(envelope.payload)))

    def payloads(self, name: str) -> list[dict[str, Any]]:
        return [p for n, p in self.events if n == name]

    def one(self, name: str) -> dict[str, Any]:
        found = self.payloads(name)
        assert len(found) == 1, f"expected exactly one {name}, got {len(found)}"
        return found[0]


# --- Gateway ---------------------------------------------------------------


def _fake_router_factory(_recorder: object) -> object:
    """A dummy router: the services store it but never call it at build time."""
    return object()


def _make_gateway(hub: EventBroadcastHub, tmp_path: Path) -> NaomiTurnGateway:
    return NaomiTurnGateway(
        hub,
        tmp_path / "naomi.db",
        _MIGRATIONS_DIR,
        router_factory=_fake_router_factory,  # type: ignore[arg-type]
        models_dir=tmp_path / "models",
    )


async def test_gateway_is_inert_before_first_listen(tmp_path: Path) -> None:
    """No orchestrator yet: state is IDLE and every delegate is a safe no-op."""
    hub = EventBroadcastHub()
    recorder = EventRecorder(hub)
    gateway = _make_gateway(hub, tmp_path)

    assert gateway.state is NaomiTurnState.IDLE  # no orchestrator → IDLE branch
    # These must not raise and must not build anything (orchestrator is None).
    await gateway.listen_stop(flush=True)
    await gateway.feed_audio_frame(
        AudioFrame(stream=StreamLabel.ME, samples=np.zeros(4, np.float32), t_start_monotonic=0.0)
    )
    await gateway.shutdown()
    assert recorder.events == []  # nothing was wired, so nothing was broadcast
    assert gateway.state is NaomiTurnState.IDLE


async def test_gateway_builds_orchestrator_once_and_delegates_state(tmp_path: Path) -> None:
    """First build is lazy + idempotent and the gateway then mirrors its state."""
    hub = EventBroadcastHub()
    gateway = _make_gateway(hub, tmp_path)

    orchestrator = await gateway._ensure_orchestrator()
    again = await gateway._ensure_orchestrator()
    assert again is orchestrator  # built exactly once (the build lock guard)
    # State now delegates to the freshly-built orchestrator, not the IDLE stub.
    assert gateway.state is orchestrator.state is NaomiTurnState.IDLE
    await gateway.shutdown()  # exercises the orchestrator-present shutdown branch


async def test_gateway_listen_start_delegates_through_injected_capture(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """listen.start drives the built orchestrator; the REAL mic seam is faked."""
    started: list[str] = []

    async def fake_capture(
        _sink: Callable[[AudioFrame], Awaitable[None]],
        **_kwargs: object,
    ) -> Callable[[], Awaitable[None]]:
        started.append("open")

        async def stop() -> None:
            started.append("stop")

        return stop

    # Replace the real mic-capture seam BEFORE the build wires it in — no
    # hardware is ever touched (mic-only, but still zero device I/O in test).
    monkeypatch.setattr(naomi_turn_gateway, "start_naomi_mic_capture", fake_capture)
    # listen.start builds a fresh Silero VAD per session; fake it (no model file).
    monkeypatch.setattr(
        naomi_turn_gateway,
        "SileroOnnxVoiceActivityDetector",
        lambda _model_path: (lambda _chunk: 0.0),
    )
    hub = EventBroadcastHub()
    gateway = _make_gateway(hub, tmp_path)

    await gateway.listen_start(open_mic=True)
    state_after_start = gateway.state
    assert state_after_start is NaomiTurnState.LISTENING  # command reached orchestrator
    assert started == ["open"]
    await gateway.feed_audio_frame(
        AudioFrame(stream=StreamLabel.ME, samples=np.zeros(4, np.float32), t_start_monotonic=0.0)
    )
    await gateway.listen_stop(flush=False)  # delegates to the built orchestrator
    state_after_stop = gateway.state
    assert state_after_stop is NaomiTurnState.IDLE  # discard-stop settled to idle
    await gateway.shutdown()
    assert "stop" in started  # capture was torn down


async def test_gateway_build_stt_vad_factory_and_transcribe_deps_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The STT closures build a fresh VAD and fail closed when STT deps absent."""
    made_vads: list[object] = []

    class FakeVad:
        def __init__(self, _model_path: Path) -> None:
            made_vads.append(self)

    monkeypatch.setattr(naomi_turn_gateway, "SileroOnnxVoiceActivityDetector", FakeVad)
    monkeypatch.setattr(naomi_turn_gateway, "stt_dependencies_available", lambda: False)
    hub = EventBroadcastHub()
    gateway = _make_gateway(hub, tmp_path)

    vad_factory, transcribe = gateway._build_stt()
    vad = vad_factory()  # a FRESH VAD per session
    assert vad is made_vads[-1]

    with pytest.raises(RuntimeError, match="STT dependencies not installed"):
        await transcribe(np.zeros(160, np.float32))  # fail closed, not a silent []


# --- Speaker ---------------------------------------------------------------


class _Clock:
    """A scripted monotonic clock: fixed readings, last value repeats."""

    def __init__(self, readings: Sequence[float]) -> None:
        self._readings = list(readings)
        self._i = 0

    def __call__(self) -> float:
        value = self._readings[min(self._i, len(self._readings) - 1)]
        self._i += 1
        return value


class FakeConnection:
    """A fake warm Cartesia connection: scripted messages, records calls."""

    def __init__(
        self, messages: Sequence[CartesiaMessage], *, raise_exc: Exception | None = None
    ) -> None:
        self._messages = list(messages)
        self._raise_exc = raise_exc
        self.speak_calls: list[tuple[tuple[str, ...], str, object]] = []
        self.cancelled: list[str] = []
        self.closed = False

    async def speak_utterance(
        self, chunks: Sequence[str], context_id: str, affect: object
    ) -> Any:
        self.speak_calls.append((tuple(chunks), context_id, affect))
        if self._raise_exc is not None:
            raise self._raise_exc
        for message in self._messages:
            yield message

    async def cancel(self, context_id: str) -> bool:
        self.cancelled.append(context_id)
        return True

    async def close(self) -> None:
        self.closed = True


class BlockingConnection:
    """A connection whose utterance parks forever (until the task is cancelled)."""

    def __init__(self) -> None:
        self.cancelled: list[str] = []
        self.closed = False
        self._never = asyncio.Event()

    async def speak_utterance(
        self, chunks: Sequence[str], context_id: str, affect: object
    ) -> Any:
        await self._never.wait()  # parks the relay so cancel has a live task
        if False:  # pragma: no cover - makes this an async generator
            yield  # type: ignore[unreachable]

    async def cancel(self, context_id: str) -> bool:
        self.cancelled.append(context_id)
        return True

    async def close(self) -> None:
        self.closed = True


def _make_speaker(
    hub: EventBroadcastHub, connection: object, *, readings: Sequence[float] = (0.0,)
) -> NaomiTurnSpeaker:
    return NaomiTurnSpeaker(hub, connection, clock=_Clock(readings))  # type: ignore[arg-type]


async def _speak_and_wait(
    speaker: NaomiTurnSpeaker,
    chunks: Sequence[str],
    affect: tuple[float, float] | None,
    on_first: Callable[[int], Awaitable[None]] | None,
) -> tuple[str, list[tuple[str, str]]]:
    """Speak, then block until the relay's finished callback fires."""
    done = asyncio.Event()
    finished: list[tuple[str, str]] = []

    async def on_fin(context_id: str, reason: str) -> None:
        finished.append((context_id, reason))
        done.set()

    speaker.set_finished_callback(on_fin)
    context_id = await speaker.speak(chunks, affect, on_first_audio=on_first)
    await asyncio.wait_for(done.wait(), timeout=2.0)
    return context_id, finished


async def test_speaker_relays_chunks_timestamps_done_with_warm_ttfa() -> None:
    """seq 0 carries the measured warm TTFA; later chunks carry none."""
    hub = EventBroadcastHub()
    recorder = EventRecorder(hub)
    messages: list[CartesiaMessage] = [
        CartesiaAudioChunk(context_id="wire", data_b64="A0"),
        CartesiaAudioChunk(context_id="wire", data_b64="A1"),
        CartesiaWordTimestamps(
            context_id="wire", words=("hi",), starts_s=(0.0,), ends_s=(0.2,)
        ),
        CartesiaDone(context_id="wire"),
    ]
    speaker = _make_speaker(hub, FakeConnection(messages), readings=(1.0, 1.045))

    ttfa_seen: list[int] = []

    async def on_first(ttfa_ms: int) -> None:
        ttfa_seen.append(ttfa_ms)

    context_id, finished = await _speak_and_wait(
        speaker, ["Hello.", "There."], (0.6, 0.5), on_first
    )

    # Honest warm TTFA = dispatch(1.0) → first audio(1.045) = 45 ms, seq 0 only.
    assert ttfa_seen == [45]
    chunks = recorder.payloads("naomi.audio.chunk")
    assert [c["seq"] for c in chunks] == [0, 1]
    assert chunks[0]["ttfa_ms"] == 45 and chunks[0]["pcm_b64"] == "A0"
    assert "ttfa_ms" not in chunks[1] and chunks[1]["pcm_b64"] == "A1"
    # All payloads carry the SPEAKER's own context_id, not the wire's.
    assert all(c["context_id"] == context_id for c in chunks)
    stamps = recorder.one("naomi.speaking.timestamps")
    assert stamps["words"] == ["hi"] and stamps["ends_s"] == [0.2]
    done = recorder.one("naomi.audio.done")
    assert done["reason"] == "completed" and done["context_id"] == context_id
    assert finished == [(context_id, "completed")]  # natural end signalled up
    assert speaker.active_context_id is None  # cleared on natural completion


async def test_speaker_error_frame_becomes_honest_error_done() -> None:
    """A provider error frame reports reason=error with the bounded detail."""
    hub = EventBroadcastHub()
    recorder = EventRecorder(hub)
    messages: list[CartesiaMessage] = [
        CartesiaErrorMessage(context_id="wire", message="rate limited")
    ]
    speaker = _make_speaker(hub, FakeConnection(messages))

    context_id, finished = await _speak_and_wait(speaker, ["Hi."], None, None)

    done = recorder.one("naomi.audio.done")
    assert done["reason"] == "error" and done["detail"] == "rate limited"
    assert finished == [(context_id, "error")]  # the orchestrator learns it failed


async def test_speaker_provider_exception_reports_error_and_finishes() -> None:
    """A raised VoiceProviderError mid-stream becomes an error done, not a crash."""
    hub = EventBroadcastHub()
    recorder = EventRecorder(hub)
    connection = FakeConnection([], raise_exc=VoiceProviderError("cartesia send failed"))
    speaker = _make_speaker(hub, connection)

    context_id, finished = await _speak_and_wait(speaker, ["Hi."], None, None)

    done = recorder.one("naomi.audio.done")
    assert done["reason"] == "error" and "cartesia send failed" in str(done["detail"])
    assert finished == [(context_id, "error")]


async def test_speaker_egress_blocked_exception_reports_error() -> None:
    """A kill-switch VoiceEgressBlockedError surfaces as an honest error done."""
    hub = EventBroadcastHub()
    recorder = EventRecorder(hub)
    speaker = _make_speaker(hub, FakeConnection([], raise_exc=VoiceEgressBlockedError()))

    _cid, finished = await _speak_and_wait(speaker, ["Hi."], None, None)

    assert recorder.one("naomi.audio.done")["reason"] == "error"
    assert finished[0][1] == "error"


async def test_speaker_cancel_is_the_barge_in_wire() -> None:
    """cancel stops the live utterance at the source and reports cancelled."""
    hub = EventBroadcastHub()
    recorder = EventRecorder(hub)
    connection = BlockingConnection()
    speaker = _make_speaker(hub, connection)

    context_id = await speaker.speak(["Hello there."], None)
    await asyncio.sleep(0)  # let the relay task reach the park point
    active = speaker.active_context_id
    assert active == context_id

    cancelled = await speaker.cancel()
    assert cancelled == context_id
    assert connection.cancelled == [context_id]  # cancel frame sent to the wire
    done = recorder.one("naomi.audio.done")
    assert done["reason"] == "cancelled" and done["context_id"] == context_id
    after_cancel_ctx = speaker.active_context_id
    assert after_cancel_ctx is None
    # Idempotent: a second cancel with nothing speaking is a clean None.
    second_cancel = await speaker.cancel()
    assert second_cancel is None


async def test_speaker_speak_cancels_the_previous_utterance_first() -> None:
    """A new utterance silences the old one so Naomi never overlaps herself."""
    hub = EventBroadcastHub()
    connection = BlockingConnection()
    speaker = _make_speaker(hub, connection)

    first = await speaker.speak(["one"], None)
    await asyncio.sleep(0)
    second = await speaker.speak(["two"], None)  # must cancel `first` first
    assert second != first
    assert connection.cancelled == [first]  # only the previous context was cancelled
    assert speaker.active_context_id == second
    await speaker.shutdown()


async def test_speaker_shutdown_silences_and_closes_the_socket() -> None:
    """Shutdown cancels any live utterance and closes the underlying socket."""
    hub = EventBroadcastHub()
    connection = BlockingConnection()
    speaker = _make_speaker(hub, connection)

    await speaker.speak(["speaking"], None)
    await asyncio.sleep(0)
    await speaker.shutdown()
    assert connection.closed is True  # socket closed on process shutdown


async def test_speaker_without_finished_callback_still_relays_and_completes() -> None:
    """No callback wired yet: a chunk with no first-audio hook still relays."""
    hub = EventBroadcastHub()
    recorder = EventRecorder(hub)
    messages: list[CartesiaMessage] = [
        CartesiaAudioChunk(context_id="wire", data_b64="A0"),
        CartesiaDone(context_id="wire"),
    ]
    # Constructed WITHOUT a finished callback and spoken WITHOUT on_first_audio.
    speaker = NaomiTurnSpeaker(hub, FakeConnection(messages), clock=_Clock((0.0,)))  # type: ignore[arg-type]
    await speaker.speak(["Hi."], None)  # on_first_audio omitted → skips the hook
    for _ in range(200):  # wait for the relay to finish (no callback to await on)
        if speaker.active_context_id is None:
            break
        await asyncio.sleep(0)

    chunks = recorder.payloads("naomi.audio.chunk")
    # seq 0 still MEASURES the warm TTFA (clock 0.0→0.0 = 0 ms); only the
    # optional first-audio hook is skipped when no callback was supplied.
    assert len(chunks) == 1 and chunks[0]["ttfa_ms"] == 0
    assert recorder.one("naomi.audio.done")["reason"] == "completed"


async def test_speaker_cancel_returns_none_when_tracked_task_already_finished() -> None:
    """Defensive branch: a done-but-still-tracked task yields no second done."""
    hub = EventBroadcastHub()
    recorder = EventRecorder(hub)
    speaker = _make_speaker(hub, FakeConnection([]))

    async def _already_done() -> None:
        return None

    task: asyncio.Task[None] = asyncio.create_task(_already_done())
    await task
    speaker._active_task = task
    speaker._active_context_id = "ctx-finished"

    assert await speaker.cancel() is None  # relay already reported its own done
    assert recorder.payloads("naomi.audio.done") == []  # no duplicate cancelled event
