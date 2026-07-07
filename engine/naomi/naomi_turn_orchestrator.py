"""The Naomi conversation-loop conductor: mic → answer → warm-socket speech.

Purpose: runs one full turn end to end and instruments every stage. On
``naomi.listen.start`` it opens a mic-only STT session; on end-of-speech it
captures the VERBATIM utterance, tries the prepare-only action path, else
answers from live-tier retrieval + router synthesis, parses the affect tag,
clause-chunks the reply, and speaks it over the persistent Cartesia socket —
broadcasting ``naomi.state`` / ``naomi.user_utterance`` / ``naomi.reply`` /
``naomi.turn.latency`` / ``naomi.turn.error`` as it goes. Auto barge-in: a
mic speech-onset while Naomi is speaking cancels playback and returns to
listening. It NEVER executes an action — it only prepares approval cards.
Pipeline position: the top of ``engine.naomi``; constructed by the loop
gateway and driven by ``naomi_turn_command_dispatcher``.

Concurrency invariant: the turn state machine IS the guard. ``_on_utterance``
checks and transitions synchronously (no await between), so under asyncio's
cooperative scheduling exactly one segment worker wins a turn — a second
utterance mid-turn is dropped, not double-run. Kill-switch/redaction live in
the router and persistent connection (fail closed on egress); this conductor
surfaces their typed failures as honest ``naomi.turn.error`` events.
"""

import uuid
from collections.abc import Awaitable, Callable

from engine.ask.ask_answer_contracts import AskCitation
from engine.audio.audio_frame_types import AudioFrame
from engine.naomi.naomi_action_intent_flow import NaomiActionIntentFlow
from engine.naomi.naomi_mic_stt_session import (
    NaomiMicSttSession,
    TranscribeFn,
    VadProbabilityFn,
)
from engine.naomi.naomi_reply_clause_chunker import chunk_reply_into_clauses
from engine.naomi.naomi_turn_latency_breakdown import NaomiTurnLatency
from engine.naomi.naomi_turn_protocol_names import (
    EVENT_NAOMI_REPLY,
    EVENT_NAOMI_STATE,
    EVENT_NAOMI_TURN_ERROR,
    EVENT_NAOMI_TURN_LATENCY,
    EVENT_NAOMI_USER_UTTERANCE,
    build_naomi_reply_payload,
    build_naomi_state_payload,
    build_naomi_turn_error_payload,
    build_naomi_user_utterance_payload,
)
from engine.naomi.naomi_turn_speaker import NaomiTurnSpeaker
from engine.naomi.naomi_turn_state_machine import (
    NaomiTurnEvent,
    NaomiTurnState,
    NaomiTurnStateMachine,
)
from engine.naomi.naomi_voice_answer_service import NaomiVoiceAnswer, NaomiVoiceAnswerService
from engine.protocol import EventBroadcastHub

# A stop callback returned by the mic capture starter (idempotent close).
StopCapture = Callable[[], Awaitable[None]]
# The capture starter: given a frame sink, open the mic and stream frames.
FrameSink = Callable[[AudioFrame], Awaitable[None]]
StartCapture = Callable[[FrameSink], Awaitable[StopCapture]]


async def _noop_stop() -> None:  # pragma: no cover - trivial default
    return None


async def _null_capture(_sink: FrameSink) -> StopCapture:  # pragma: no cover - default
    """Default when no mic backend is wired: frames arrive via feed_audio_frame."""
    return _noop_stop


class NaomiTurnOrchestrator:
    """Owns the loop state; one turn at a time; barge-in aware."""

    def __init__(
        self,
        hub: EventBroadcastHub,
        answer_service: NaomiVoiceAnswerService,
        action_flow: NaomiActionIntentFlow,
        speaker: NaomiTurnSpeaker,
        vad_factory: Callable[[], VadProbabilityFn],
        transcribe: TranscribeFn,
        *,
        clock: Callable[[], float],
        start_capture: StartCapture = _null_capture,
    ) -> None:
        self._hub = hub
        self._answer_service = answer_service
        self._action_flow = action_flow
        self._speaker = speaker
        # A FRESH stateful Silero VAD per listening session (new audio stream,
        # reset anchor); Parakeet is stateless per window so it is shared.
        self._vad_factory = vad_factory
        self._transcribe = transcribe
        self._clock = clock
        self._start_capture = start_capture
        self._machine = NaomiTurnStateMachine()
        self._open_mic = False
        self._session: NaomiMicSttSession | None = None
        self._stop_capture: StopCapture | None = None

    @property
    def state(self) -> NaomiTurnState:
        return self._machine.state

    # -- command surface -----------------------------------------------------

    async def listen_start(self, open_mic: bool) -> None:
        """Open the mic session and begin listening (idempotent if listening)."""
        if not self._machine.can_apply(NaomiTurnEvent.START_LISTENING):
            return  # already in a turn/listening — the command is a no-op
        self._open_mic = open_mic
        self._session = NaomiMicSttSession(
            self._vad_factory(),
            self._transcribe,
            anchor_monotonic=self._clock(),
            on_utterance=self._on_utterance,
            on_speech_onset=self._on_speech_onset,
            clock=self._clock,
        )
        self._stop_capture = await self._start_capture(self.feed_audio_frame)
        await self._transition(NaomiTurnEvent.START_LISTENING)

    async def listen_stop(self, flush: bool) -> None:
        """Close the mic. ``flush`` forces the pending speech into a turn."""
        await self._close_capture()
        session = self._session
        if flush and session is not None:
            # Push-to-talk release: finalize forces the VAD end-point, which
            # fires _on_utterance for the pending speech (if any was heard).
            await session.finalize()
        self._session = None
        if not flush and self._machine.can_apply(NaomiTurnEvent.STOP):
            # Discarding pending audio: settle straight to idle.
            await self._transition(NaomiTurnEvent.STOP)

    async def feed_audio_frame(self, frame: AudioFrame) -> None:
        """The audio seam: mic backend (or the live test) pushes frames here."""
        session = self._session
        if session is not None:
            await session.feed(frame)

    async def shutdown(self) -> None:
        """Process shutdown: stop capture and silence the speaker/socket."""
        await self._close_capture()
        self._session = None
        await self._speaker.shutdown()

    # -- turn pipeline -------------------------------------------------------

    async def _on_utterance(self, text: str, endpoint_ms: int) -> None:
        """A verbatim utterance was end-pointed: run exactly one turn."""
        # Atomic guard (no await before the transition): only a LISTENING
        # state may begin a turn, so a second utterance mid-turn is dropped.
        if self._machine.state is not NaomiTurnState.LISTENING:
            return
        self._machine.apply(NaomiTurnEvent.CAPTURE_UTTERANCE)
        turn_id = uuid.uuid4().hex
        await self._broadcast_state(turn_id)
        await self._hub.broadcast_event(
            EVENT_NAOMI_USER_UTTERANCE, build_naomi_user_utterance_payload(turn_id, text)
        )
        try:
            await self._answer_or_act(turn_id, text, endpoint_ms)
        except Exception as exc:
            await self._fail_turn(turn_id, exc)

    async def _answer_or_act(self, turn_id: str, text: str, endpoint_ms: int) -> None:
        """Prepare an action (if any) else answer; then speak the reply."""
        action = await self._action_flow.maybe_prepare_action(text)
        if action is not None:
            await self._speak_reply(
                turn_id,
                reply_text=action.spoken_confirmation,
                affect_triple=None,
                cartesia_affect=None,
                citations=(),
                no_answer=False,
                action_card_id=action.card_id,
                endpoint_ms=endpoint_ms,
                retrieval_ms=0,
                llm_ms=action.llm_ms,
            )
            return
        answer: NaomiVoiceAnswer = await self._answer_service.answer(text)
        affect_triple = None if answer.affect is None else answer.affect.as_wire_triple()
        cartesia_affect = None if answer.affect is None else answer.affect.as_cartesia_tuple()
        await self._speak_reply(
            turn_id,
            reply_text=answer.spoken_text,
            affect_triple=affect_triple,
            cartesia_affect=cartesia_affect,
            citations=answer.citations,
            no_answer=answer.no_answer,
            action_card_id=None,
            endpoint_ms=endpoint_ms,
            retrieval_ms=answer.retrieval_ms,
            llm_ms=answer.llm_ms,
        )

    async def _speak_reply(
        self,
        turn_id: str,
        *,
        reply_text: str,
        affect_triple: tuple[float, float, str | None] | None,
        cartesia_affect: tuple[float, float] | None,
        citations: tuple[AskCitation, ...],
        no_answer: bool,
        action_card_id: int | None,
        endpoint_ms: int,
        retrieval_ms: int,
        llm_ms: int,
    ) -> None:
        """Broadcast the reply, then speak it over the warm socket."""
        await self._hub.broadcast_event(
            EVENT_NAOMI_REPLY,
            build_naomi_reply_payload(
                turn_id, reply_text, affect_triple, citations, no_answer, action_card_id
            ),
        )
        chunks = chunk_reply_into_clauses(reply_text)
        if not chunks:  # pragma: no cover - reply text is always non-empty here
            await self._finish_turn()
            return
        self._machine.apply(NaomiTurnEvent.BEGIN_SPEAKING)
        await self._broadcast_state(turn_id)

        async def _emit_latency(ttfa_ms: int) -> None:
            latency = NaomiTurnLatency(
                endpoint_ms=endpoint_ms,
                retrieval_ms=retrieval_ms,
                llm_ms=llm_ms,
                ttfa_ms=ttfa_ms,
            )
            await self._hub.broadcast_event(
                EVENT_NAOMI_TURN_LATENCY, latency.as_event_payload(turn_id)
            )

        await self._speaker.speak(chunks, cartesia_affect, on_first_audio=_emit_latency)

    # -- speaker + barge-in callbacks ---------------------------------------

    async def on_speaker_finished(self, _context_id: str, reason: str) -> None:
        """The utterance ended naturally (or errored) — advance the loop."""
        if self._machine.state is not NaomiTurnState.SPEAKING:
            return  # a barge-in already moved us on; ignore the late signal
        if reason == "error":
            await self._transition_terminal(NaomiTurnEvent.FAIL)
        else:
            await self._finish_turn()

    async def _on_speech_onset(self) -> None:
        """Mic onset: barge-in ONLY while speaking (else a normal turn start)."""
        if self._machine.state is not NaomiTurnState.SPEAKING:
            return
        # Perceived-stop < 50ms: cancel generation at the source; the UI ducks
        # playback locally the instant it sees the listening state.
        await self._speaker.cancel()
        self._machine.apply(NaomiTurnEvent.BARGE_IN)
        await self._broadcast_state(None)

    # -- helpers -------------------------------------------------------------

    async def _finish_turn(self) -> None:
        await self._transition_terminal(NaomiTurnEvent.FINISH_TURN)

    async def _transition_terminal(self, event: NaomiTurnEvent) -> None:
        """A finishing/failing transition (resume-dependent), then broadcast.

        When the mic stays open the loop returns to LISTENING for the next
        turn; otherwise it settles to IDLE and the session is torn down.
        """
        self._machine.apply(event, resume=self._open_mic)
        if self._machine.state is NaomiTurnState.IDLE:
            await self._close_capture()
            self._session = None
        await self._broadcast_state(None)

    async def _fail_turn(self, turn_id: str, exc: Exception) -> None:
        """Surface an honest turn error and settle the state machine."""
        await self._hub.broadcast_event(
            EVENT_NAOMI_TURN_ERROR, build_naomi_turn_error_payload(str(exc), turn_id)
        )
        if self._machine.state in (NaomiTurnState.THINKING, NaomiTurnState.SPEAKING):
            await self._transition_terminal(NaomiTurnEvent.FAIL)

    async def _transition(self, event: NaomiTurnEvent) -> None:
        self._machine.apply(event, resume=self._open_mic)
        await self._broadcast_state(None)

    async def _broadcast_state(self, turn_id: str | None) -> None:
        await self._hub.broadcast_event(
            EVENT_NAOMI_STATE, build_naomi_state_payload(self._machine.state.value, turn_id)
        )

    async def _close_capture(self) -> None:
        stop = self._stop_capture
        self._stop_capture = None
        if stop is not None:
            await stop()
