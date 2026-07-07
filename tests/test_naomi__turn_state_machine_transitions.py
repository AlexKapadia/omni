"""Naomi turn state machine: legal transitions, illegal ones, resume branch.

Adversarial intent: enumerate the ENTIRE (state x event) space and assert the
exact target for every legal pair and that every illegal pair raises — a
transition table with a wrong or missing edge would leave the pool showing a
state Naomi is not in. The resume-dependent terminals are checked in both
open-mic (loop) and push-to-talk (settle) modes.
"""

import itertools

import pytest

from engine.naomi.naomi_turn_state_machine import (
    IllegalNaomiTransition,
    NaomiTurnEvent,
    NaomiTurnState,
    NaomiTurnStateMachine,
    resolve_transition,
)

S = NaomiTurnState
E = NaomiTurnEvent

# The COMPLETE legal transition map (resume-independent target, or a marker
# that the target is resume-dependent). Anything not here must raise.
_STATIC_LEGAL: dict[tuple[NaomiTurnState, NaomiTurnEvent], NaomiTurnState] = {
    (S.IDLE, E.START_LISTENING): S.LISTENING,
    (S.LISTENING, E.CAPTURE_UTTERANCE): S.THINKING,
    (S.LISTENING, E.STOP): S.IDLE,
    (S.LISTENING, E.FAIL): S.IDLE,
    (S.THINKING, E.BEGIN_SPEAKING): S.SPEAKING,
    (S.THINKING, E.STOP): S.IDLE,
    (S.SPEAKING, E.BARGE_IN): S.LISTENING,
    (S.SPEAKING, E.STOP): S.IDLE,
}
_RESUME_DEPENDENT = {
    (S.THINKING, E.FAIL),
    (S.SPEAKING, E.FINISH_TURN),
    (S.SPEAKING, E.FAIL),
}


@pytest.mark.parametrize("state", list(S))
@pytest.mark.parametrize("event", list(E))
def test_every_state_event_pair_is_either_defined_or_raises(
    state: NaomiTurnState, event: NaomiTurnEvent
) -> None:
    key = (state, event)
    if key in _STATIC_LEGAL:
        assert resolve_transition(state, event, resume=False) is _STATIC_LEGAL[key]
        assert resolve_transition(state, event, resume=True) is _STATIC_LEGAL[key]
    elif key in _RESUME_DEPENDENT:
        assert resolve_transition(state, event, resume=True) is S.LISTENING
        assert resolve_transition(state, event, resume=False) is S.IDLE
    else:
        with pytest.raises(IllegalNaomiTransition) as excinfo:
            resolve_transition(state, event, resume=False)
        assert excinfo.value.state is state
        assert excinfo.value.event is event


def test_all_pairs_are_accounted_for() -> None:
    """No (state, event) pair is silently missing from BOTH maps + illegal."""
    total = len(list(S)) * len(list(E))
    covered = len(_STATIC_LEGAL) + len(_RESUME_DEPENDENT)
    # The remainder must all be illegal; this asserts the test itself is total.
    illegal = total - covered
    assert illegal > 0  # sanity: some transitions ARE illegal
    for state, event in itertools.product(S, E):
        key = (state, event)
        legal = key in _STATIC_LEGAL or key in _RESUME_DEPENDENT
        assert legal == NaomiTurnStateMachine(state).can_apply(event)


def test_happy_path_open_mic_loops_back_to_listening() -> None:
    machine = NaomiTurnStateMachine()
    assert machine.apply(E.START_LISTENING) is S.LISTENING
    assert machine.apply(E.CAPTURE_UTTERANCE) is S.THINKING
    assert machine.apply(E.BEGIN_SPEAKING) is S.SPEAKING
    # Open mic: the turn finishes back into LISTENING for the next utterance.
    assert machine.apply(E.FINISH_TURN, resume=True) is S.LISTENING


def test_happy_path_push_to_talk_settles_to_idle() -> None:
    machine = NaomiTurnStateMachine()
    machine.apply(E.START_LISTENING)
    machine.apply(E.CAPTURE_UTTERANCE)
    machine.apply(E.BEGIN_SPEAKING)
    assert machine.apply(E.FINISH_TURN, resume=False) is S.IDLE


def test_barge_in_only_legal_from_speaking() -> None:
    machine = NaomiTurnStateMachine()
    machine.apply(E.START_LISTENING)
    with pytest.raises(IllegalNaomiTransition):
        machine.apply(E.BARGE_IN)  # cannot barge in while merely listening


def test_second_capture_mid_turn_is_illegal() -> None:
    """The orchestrator's atomic guard relies on THINKING refusing a capture."""
    machine = NaomiTurnStateMachine()
    machine.apply(E.START_LISTENING)
    machine.apply(E.CAPTURE_UTTERANCE)
    assert machine.state is S.THINKING
    with pytest.raises(IllegalNaomiTransition):
        machine.apply(E.CAPTURE_UTTERANCE)
