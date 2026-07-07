"""The Naomi turn-loop state machine: idle → listening → thinking → speaking.

Purpose: the single, pure, deterministic authority over which conversation
state Naomi is in, and which transitions are legal. Every visual and audio
consequence keys off ``naomi.state`` (docs/design/naomi-visual-brief.md §2),
so this machine must NEVER enter an inconsistent state — an illegal
transition raises rather than silently corrupting the loop.
Pipeline position: owned by ``engine.naomi.naomi_turn_orchestrator``; the
orchestrator applies one event per real-world moment and broadcasts the
resulting state.

Design: a pure transition table. Two terminal transitions (a finished turn
and a mid-turn failure) branch on ``resume`` — the open-mic flag — so a
conversation either loops back to LISTENING (open mic) or settles to IDLE
(push-to-talk). No I/O, no time, no randomness: identical inputs always
yield the identical next state (determinism is tested).
"""

from enum import StrEnum


class NaomiTurnState(StrEnum):
    """The four conversation states the pool and captions render."""

    IDLE = "idle"
    LISTENING = "listening"
    THINKING = "thinking"
    SPEAKING = "speaking"


class NaomiTurnEvent(StrEnum):
    """The real-world moments that move the loop (one per orchestrator step)."""

    START_LISTENING = "start_listening"  # open the mic (push-to-talk or open-mic)
    CAPTURE_UTTERANCE = "capture_utterance"  # VAD end-point: a verbatim turn exists
    BEGIN_SPEAKING = "begin_speaking"  # the reply is ready; TTS is dispatched
    FINISH_TURN = "finish_turn"  # playback done (naomi.audio.done completed)
    BARGE_IN = "barge_in"  # the user talked over Naomi (mic onset while speaking)
    STOP = "stop"  # the user closed the mic (listen.stop, no pending turn)
    FAIL = "fail"  # an honest failure aborted the turn


class IllegalNaomiTransition(Exception):
    """A (state, event) pair that must never happen — a loop-logic bug.

    Raised rather than swallowed so a mis-sequenced orchestrator step is
    caught loudly in tests instead of leaving Naomi in a wrong state.
    """

    def __init__(self, state: NaomiTurnState, event: NaomiTurnEvent) -> None:
        super().__init__(f"illegal Naomi transition: {event.value} while {state.value}")
        self.state = state
        self.event = event


# Static transitions that do NOT depend on the open-mic flag.
_STATIC_TRANSITIONS: dict[tuple[NaomiTurnState, NaomiTurnEvent], NaomiTurnState] = {
    (NaomiTurnState.IDLE, NaomiTurnEvent.START_LISTENING): NaomiTurnState.LISTENING,
    (NaomiTurnState.LISTENING, NaomiTurnEvent.CAPTURE_UTTERANCE): NaomiTurnState.THINKING,
    (NaomiTurnState.LISTENING, NaomiTurnEvent.STOP): NaomiTurnState.IDLE,
    (NaomiTurnState.LISTENING, NaomiTurnEvent.FAIL): NaomiTurnState.IDLE,
    (NaomiTurnState.THINKING, NaomiTurnEvent.BEGIN_SPEAKING): NaomiTurnState.SPEAKING,
    (NaomiTurnState.THINKING, NaomiTurnEvent.STOP): NaomiTurnState.IDLE,
    (NaomiTurnState.SPEAKING, NaomiTurnEvent.BARGE_IN): NaomiTurnState.LISTENING,
    (NaomiTurnState.SPEAKING, NaomiTurnEvent.STOP): NaomiTurnState.IDLE,
}

# Terminal transitions whose target depends on ``resume`` (the open-mic flag):
# a finished/failed turn loops back to LISTENING when the mic stays open, else
# settles to IDLE. Kept as a set so the resume branch is applied in one place.
_RESUME_DEPENDENT: frozenset[tuple[NaomiTurnState, NaomiTurnEvent]] = frozenset(
    {
        (NaomiTurnState.THINKING, NaomiTurnEvent.FAIL),
        (NaomiTurnState.SPEAKING, NaomiTurnEvent.FINISH_TURN),
        (NaomiTurnState.SPEAKING, NaomiTurnEvent.FAIL),
    }
)


def resolve_transition(
    state: NaomiTurnState, event: NaomiTurnEvent, *, resume: bool
) -> NaomiTurnState:
    """Return the next state for ``(state, event)``; raise if illegal.

    ``resume`` (the open-mic flag) selects the target of the two terminal,
    resume-dependent transitions; it is ignored for every static transition.
    Pure and total over the legal domain — no side effects.
    """
    key = (state, event)
    if key in _RESUME_DEPENDENT:
        return NaomiTurnState.LISTENING if resume else NaomiTurnState.IDLE
    target = _STATIC_TRANSITIONS.get(key)
    if target is None:
        raise IllegalNaomiTransition(state, event)
    return target


class NaomiTurnStateMachine:
    """A tiny stateful wrapper the orchestrator drives one event at a time."""

    def __init__(self, initial: NaomiTurnState = NaomiTurnState.IDLE) -> None:
        self._state = initial

    @property
    def state(self) -> NaomiTurnState:
        return self._state

    def apply(self, event: NaomiTurnEvent, *, resume: bool = False) -> NaomiTurnState:
        """Apply one event, updating and returning the state (raises if illegal)."""
        self._state = resolve_transition(self._state, event, resume=resume)
        return self._state

    def can_apply(self, event: NaomiTurnEvent) -> bool:
        """True when ``event`` is legal from the current state (no mutation)."""
        key = (self._state, event)
        return key in _RESUME_DEPENDENT or key in _STATIC_TRANSITIONS
