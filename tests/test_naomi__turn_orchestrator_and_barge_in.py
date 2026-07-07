"""Naomi turn orchestrator: full-turn event sequence + auto barge-in races.

Adversarial intent:
- A full turn broadcasts the EXACT ordered sequence the UI keys off:
  state=listening → state=thinking + verbatim user_utterance → reply →
  state=speaking → turn.latency (on first audio) → terminal state.
- Auto barge-in: a mic onset WHILE speaking cancels the speaker and returns to
  listening (< perceived stop); an onset when NOT speaking is a no-op (race
  after the turn finished must not spuriously cancel).
- The action path speaks a prepared-card confirmation and NEVER calls the
  answer service (prepare-only).
"""

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

import numpy as np
import numpy.typing as npt

from engine.ask.ask_answer_contracts import AskCitation
from engine.audio.audio_frame_types import PIPELINE_SAMPLE_RATE, AudioFrame, StreamLabel
from engine.naomi.affect_self_tag_parser import ParsedAffect
from engine.naomi.naomi_action_intent_flow import NaomiActionResult
from engine.naomi.naomi_turn_orchestrator import NaomiTurnOrchestrator
from engine.naomi.naomi_turn_state_machine import NaomiTurnState
from engine.naomi.naomi_voice_answer_service import NaomiVoiceAnswer
from engine.protocol import EventBroadcastHub
from engine.protocol.websocket_envelope import Envelope
from engine.stt.word_token_types import WordToken

_CHUNK = 512
_CHUNK_S = _CHUNK / PIPELINE_SAMPLE_RATE

CITATION = AskCitation(
    n=1,
    note_path="Clients/Henderson.md",
    line_start=10,
    line_end=12,
    heading_path="Contract",
    quote="due August 15th",
)


class EventRecorder:
    """Subscribes to the hub and records (name, payload) in order."""

    def __init__(self, hub: EventBroadcastHub) -> None:
        self.events: list[tuple[str, dict[str, Any]]] = []
        hub.subscribe(self._send)

    async def _send(self, envelope: Envelope) -> None:
        self.events.append((envelope.name, dict(envelope.payload)))

    def states(self) -> list[str]:
        return [str(p["state"]) for n, p in self.events if n == "naomi.state"]

    def first(self, name: str) -> dict[str, Any]:
        for n, payload in self.events:
            if n == name:
                return payload
        raise AssertionError(f"no {name} event recorded")


class FakeAnswerService:
    def __init__(self) -> None:
        self.calls = 0

    async def answer(self, utterance: str) -> NaomiVoiceAnswer:
        self.calls += 1
        return NaomiVoiceAnswer(
            spoken_text="The renewal is due August 15th.",
            affect=ParsedAffect(valence=0.6, arousal=0.5),
            citations=(CITATION,),
            no_answer=False,
            retrieval_ms=12,
            llm_ms=200,
        )


class NoActionFlow:
    async def maybe_prepare_action(self, _utterance: str) -> NaomiActionResult | None:
        return None


class CardActionFlow:
    async def maybe_prepare_action(self, _utterance: str) -> NaomiActionResult:
        return NaomiActionResult(
            card_id=7,
            card_type="create_event",
            spoken_confirmation="I've prepared a calendar event.",
            llm_ms=180,
        )


class FakeSpeaker:
    """Records speak/cancel; fires first-audio; holds 'speaking' until told."""

    def __init__(self, ttfa: int = 45) -> None:
        self.speak_calls: list[tuple[tuple[str, ...], object]] = []
        self.cancels = 0
        self._on_finished: Callable[[str, str], Awaitable[None]] | None = None
        self._ttfa = ttfa

    def set_finished_callback(self, cb: Callable[[str, str], Awaitable[None]]) -> None:
        self._on_finished = cb

    async def speak(
        self,
        chunks: object,
        affect: object,
        on_first_audio: Callable[[int], Awaitable[None]] | None = None,
    ) -> str:
        self.speak_calls.append((tuple(chunks), affect))  # type: ignore[arg-type]
        if on_first_audio is not None:
            await on_first_audio(self._ttfa)
        return "ctx-fake"

    async def cancel(self) -> str:
        self.cancels += 1
        return "ctx-fake"

    async def finish(self) -> None:
        if self._on_finished is not None:
            await self._on_finished("ctx-fake", "completed")

    async def shutdown(self) -> None:
        return None


class _AmplitudeVad:
    def __call__(self, chunk: npt.NDArray[np.float32]) -> float:
        return 0.95 if float(np.abs(chunk).max()) > 0.01 else 0.02


async def _transcribe_fixed(_samples: npt.NDArray[np.float32]) -> list[WordToken]:
    return [WordToken("hello", 0.0, 0.1)]


def _frame(index: int, *, speech: bool) -> AudioFrame:
    fill = np.full(_CHUNK, 0.5, dtype=np.float32)
    samples = fill if speech else np.zeros(_CHUNK, dtype=np.float32)
    return AudioFrame(stream=StreamLabel.ME, samples=samples, t_start_monotonic=index * _CHUNK_S)


def _build(
    hub: EventBroadcastHub,
    speaker: FakeSpeaker,
    action_flow: object,
    answer_service: object,
    *,
    clock: Callable[[], float],
) -> NaomiTurnOrchestrator:
    orch = NaomiTurnOrchestrator(
        hub,
        answer_service,  # type: ignore[arg-type]
        action_flow,  # type: ignore[arg-type]
        speaker,  # type: ignore[arg-type]
        vad_factory=lambda: _AmplitudeVad(),
        transcribe=_transcribe_fixed,
        clock=clock,
    )
    speaker.set_finished_callback(orch.on_speaker_finished)
    return orch


async def _feed_one_utterance(
    orch: NaomiTurnOrchestrator, now: dict[str, float], start: int, silence: int
) -> int:
    index = start
    for _ in range(16):  # ~500ms speech
        now["t"] = index * _CHUNK_S
        await orch.feed_audio_frame(_frame(index, speech=True))
        index += 1
    for _ in range(silence):  # silence to end-point
        now["t"] = index * _CHUNK_S
        await orch.feed_audio_frame(_frame(index, speech=False))
        index += 1
    return index


def _state_of(orch: NaomiTurnOrchestrator) -> NaomiTurnState:
    """Read the live state through a call so mypy re-widens it each time
    (a bare ``orch.state`` property read gets narrowed across awaits)."""
    return orch.state


async def _await_state(orch: NaomiTurnOrchestrator, target: NaomiTurnState) -> None:
    """The turn runs in a background segment-worker task; yield until it lands.

    Bounded so a stuck turn fails loudly instead of hanging the suite.
    """
    for _ in range(500):
        if orch.state is target:
            return
        await asyncio.sleep(0)
    raise AssertionError(f"orchestrator never reached {target} (stuck at {orch.state})")


async def test_full_turn_broadcasts_the_expected_ordered_sequence() -> None:
    hub = EventBroadcastHub()
    recorder = EventRecorder(hub)
    speaker = FakeSpeaker()
    answer = FakeAnswerService()
    now = {"t": 0.0}
    orch = _build(hub, speaker, NoActionFlow(), answer, clock=lambda: now["t"])

    await orch.listen_start(open_mic=False)
    assert _state_of(orch) == NaomiTurnState.LISTENING
    await _feed_one_utterance(orch, now, 0, 26)
    await orch.listen_stop(flush=True)  # push-to-talk release forces the endpoint

    # The verbatim user text and grounded reply were broadcast.
    assert recorder.first("naomi.user_utterance")["text"] == "hello"
    reply = recorder.first("naomi.reply")
    assert reply["text"] == "The renewal is due August 15th."
    assert reply["affect"] == {"v": 0.6, "a": 0.5}
    assert reply["citations"][0]["note_path"] == "Clients/Henderson.md"
    assert reply["no_answer"] is False

    # Latency event carries the exact composed total (endpoint+retr+llm+ttfa).
    latency = recorder.first("naomi.turn.latency")
    assert latency["retrieval_ms"] == 12 and latency["llm_ms"] == 200 and latency["ttfa_ms"] == 45
    assert latency["total_ms"] == latency["endpoint_ms"] + 12 + 200 + 45

    # State order: listening → thinking → speaking (before the finish).
    assert recorder.states()[:3] == ["listening", "thinking", "speaking"]
    assert speaker.speak_calls  # the reply was actually spoken

    # Natural completion (push-to-talk) settles to idle.
    await speaker.finish()
    assert _state_of(orch) == NaomiTurnState.IDLE
    assert recorder.states()[-1] == "idle"


async def test_barge_in_while_speaking_cancels_and_returns_to_listening() -> None:
    hub = EventBroadcastHub()
    recorder = EventRecorder(hub)
    speaker = FakeSpeaker()
    now = {"t": 0.0}
    orch = _build(hub, speaker, NoActionFlow(), FakeAnswerService(), clock=lambda: now["t"])

    await orch.listen_start(open_mic=True)  # open mic: barge-in is possible
    index = await _feed_one_utterance(orch, now, 0, 26)
    await _await_state(orch, NaomiTurnState.SPEAKING)  # turn 1 reaches speaking
    assert _state_of(orch) == NaomiTurnState.SPEAKING  # turn 1 is speaking (fake holds)
    assert speaker.cancels == 0

    # The user talks over Naomi: a fresh speech burst → onset → barge-in.
    for _ in range(4):
        now["t"] = index * _CHUNK_S
        await orch.feed_audio_frame(_frame(index, speech=True))
        index += 1

    assert speaker.cancels == 1  # generation cancelled at the source
    assert _state_of(orch) == NaomiTurnState.LISTENING  # swallowed back to listening
    assert recorder.states()[-1] == "listening"


async def test_onset_after_turn_finished_does_not_spuriously_cancel() -> None:
    hub = EventBroadcastHub()
    speaker = FakeSpeaker()
    now = {"t": 0.0}
    orch = _build(hub, speaker, NoActionFlow(), FakeAnswerService(), clock=lambda: now["t"])

    await orch.listen_start(open_mic=True)
    index = await _feed_one_utterance(orch, now, 0, 26)
    await _await_state(orch, NaomiTurnState.SPEAKING)
    await speaker.finish()  # turn completes → back to listening
    assert _state_of(orch) == NaomiTurnState.LISTENING
    cancels_before = speaker.cancels

    # A speech burst now is a NEW turn's onset, not a barge-in (not speaking).
    for _ in range(4):
        now["t"] = index * _CHUNK_S
        await orch.feed_audio_frame(_frame(index, speech=True))
        index += 1
    assert speaker.cancels == cancels_before  # no spurious cancel


async def test_action_turn_speaks_confirmation_and_skips_answer_service() -> None:
    hub = EventBroadcastHub()
    recorder = EventRecorder(hub)
    speaker = FakeSpeaker()
    answer = FakeAnswerService()
    now = {"t": 0.0}
    orch = _build(hub, speaker, CardActionFlow(), answer, clock=lambda: now["t"])

    await orch.listen_start(open_mic=False)
    await _feed_one_utterance(orch, now, 0, 26)
    await orch.listen_stop(flush=True)

    reply = recorder.first("naomi.reply")
    assert reply["action_card_id"] == 7
    assert "prepared" in reply["text"].lower()
    assert answer.calls == 0  # prepare-only: the answer service was NOT consulted
    # Latency uses the action's llm span and zero retrieval.
    latency = recorder.first("naomi.turn.latency")
    assert latency["retrieval_ms"] == 0 and latency["llm_ms"] == 180
