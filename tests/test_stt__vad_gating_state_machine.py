"""VAD gate state machine: transitions, hysteresis, min-duration edges.

The gate decides what audio the transcriber ever sees, so its boundary
semantics are pinned EXACTLY: runs equal to the minimum duration count
(>=), open events are stamped retroactively at speech start, close events
at silence start, and garbage probabilities fail closed.
"""

import pytest

from engine.stt.vad_gating_state_machine import (
    VadGateConfig,
    VadGateEvent,
    VadGatingStateMachine,
)

# 32 ms chunks, like the real Silero cadence.
CHUNK = 0.032


def run_probs(
    machine: VadGatingStateMachine, probabilities: list[float], start: float = 0.0
) -> list[tuple[VadGateEvent, float]]:
    """Feed a probability script; collect every emitted event."""
    events = []
    for i, probability in enumerate(probabilities):
        t0 = start + i * CHUNK
        events.extend(machine.process(probability, t0, t0 + CHUNK))
    return events


def machine_with(
    min_speech_s: float = 0.25, min_silence_s: float = 0.6
) -> VadGatingStateMachine:
    return VadGatingStateMachine(
        VadGateConfig(min_speech_s=min_speech_s, min_silence_s=min_silence_s)
    )


def in_speech(machine: VadGatingStateMachine) -> bool:
    """Read the property through a function boundary — mypy narrows member
    expressions and does not reset them across mutating calls."""
    return machine.is_in_speech


def test_silence_only_never_emits_anything() -> None:
    machine = machine_with()
    assert run_probs(machine, [0.0] * 100) == []
    assert not machine.is_in_speech


def test_speech_run_exactly_at_min_speech_opens_boundary_exact() -> None:
    """min_speech = 8 chunks * 32 ms = 0.256 s: the 8th chunk end hits it."""
    machine = machine_with(min_speech_s=8 * CHUNK)
    events = run_probs(machine, [0.9] * 8)
    assert events == [(VadGateEvent.SEGMENT_OPEN, 0.0)]  # Retroactive stamp.


def test_speech_run_just_under_min_speech_never_opens() -> None:
    machine = machine_with(min_speech_s=8 * CHUNK)
    events = run_probs(machine, [0.9] * 7 + [0.1] * 30)
    assert events == []  # False trigger: 7 chunks < 8-chunk minimum.


def test_open_timestamp_is_the_candidate_start_not_the_confirmation_time() -> None:
    machine = machine_with(min_speech_s=0.25)
    # 10 silent chunks first: candidate starts at chunk 10 -> t = 0.32.
    events = run_probs(machine, [0.0] * 10 + [0.9] * 20)
    assert len(events) == 1
    event, t_open = events[0]
    assert event is VadGateEvent.SEGMENT_OPEN
    assert t_open == pytest.approx(10 * CHUNK)


def test_silence_run_exactly_at_min_silence_closes_boundary_exact() -> None:
    machine = machine_with(min_speech_s=0.064, min_silence_s=10 * CHUNK)
    probs = [0.9] * 20 + [0.1] * 10  # Silence run ends exactly at the minimum.
    events = run_probs(machine, probs)
    assert events[0][0] is VadGateEvent.SEGMENT_OPEN
    close_event, close_time = events[1]
    assert close_event is VadGateEvent.SEGMENT_CLOSE
    assert close_time == pytest.approx(20 * CHUNK)
    assert not machine.is_in_speech


def test_silence_just_under_min_silence_keeps_the_segment_open() -> None:
    machine = machine_with(min_speech_s=0.064, min_silence_s=10 * CHUNK)
    probs = [0.9] * 20 + [0.1] * 9 + [0.9] * 5  # Pause of 9 chunks, then speech resumes.
    events = run_probs(machine, probs)
    assert [e for e, _ in events] == [VadGateEvent.SEGMENT_OPEN]  # No close.
    assert machine.is_in_speech


def test_hysteresis_probability_between_exit_and_enter_sustains_speech() -> None:
    """0.4 sits between exit (0.35) and enter (0.5): sustains an open
    segment but never starts one."""
    sustaining = machine_with(min_speech_s=0.064)
    events = run_probs(sustaining, [0.9] * 5 + [0.4] * 50)
    assert [e for e, _ in events] == [VadGateEvent.SEGMENT_OPEN]
    assert sustaining.is_in_speech  # 0.4 never dropped below exit.

    never_starting = machine_with()
    assert run_probs(never_starting, [0.4] * 100) == []


def test_threshold_edges_enter_at_exactly_050_exit_below_035() -> None:
    """Boundary-exact thresholds: p == enter starts; p == exit sustains."""
    machine = machine_with(min_speech_s=0.064)
    events = run_probs(machine, [0.5] * 5)  # p == enter_threshold starts speech.
    assert [e for e, _ in events] == [VadGateEvent.SEGMENT_OPEN]
    run_probs(machine, [0.35] * 100, start=5 * CHUNK)  # p == exit sustains (>= exit).
    assert machine.is_in_speech


def test_full_conversation_script_produces_exact_segment_sequence() -> None:
    """Metamorphic run: two utterances -> exactly two open/close pairs with
    exact timestamps."""
    machine = machine_with(min_speech_s=0.25, min_silence_s=0.6)
    script = [0.0] * 10 + [0.95] * 40 + [0.05] * 30 + [0.9] * 30 + [0.02] * 40
    events = run_probs(machine, script)
    kinds = [e for e, _ in events]
    assert kinds == [
        VadGateEvent.SEGMENT_OPEN,
        VadGateEvent.SEGMENT_CLOSE,
        VadGateEvent.SEGMENT_OPEN,
        VadGateEvent.SEGMENT_CLOSE,
    ]
    times = [t for _, t in events]
    assert times[0] == pytest.approx(10 * CHUNK)  # First speech start.
    assert times[1] == pytest.approx(50 * CHUNK)  # First silence start.
    assert times[2] == pytest.approx(80 * CHUNK)  # Second speech start.
    assert times[3] == pytest.approx(110 * CHUNK)  # Second silence start.


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), -0.001, 1.001, -5.0, 2.0])
def test_garbage_probabilities_fail_closed(bad: float) -> None:
    machine = machine_with()
    with pytest.raises(ValueError, match="must be in"):
        machine.process(bad, 0.0, CHUNK)


def test_probability_boundaries_zero_and_one_are_legal() -> None:
    machine = machine_with()
    machine.process(0.0, 0.0, CHUNK)
    machine.process(1.0, CHUNK, 2 * CHUNK)


def test_force_close_emits_close_only_when_a_segment_is_open() -> None:
    machine = machine_with(min_speech_s=0.064)
    assert machine.force_close(1.0) == []  # Idle: nothing to close.
    run_probs(machine, [0.9] * 5)
    assert in_speech(machine)
    assert machine.force_close(5 * CHUNK) == [(VadGateEvent.SEGMENT_CLOSE, 5 * CHUNK)]
    assert not in_speech(machine)
    assert machine.force_close(5 * CHUNK) == []  # Idempotent.


def test_pending_unconfirmed_speech_is_discarded_by_force_close() -> None:
    machine = machine_with(min_speech_s=1.0)
    run_probs(machine, [0.9] * 3)  # Pending, never confirmed.
    assert machine.force_close(3 * CHUNK) == []


def test_invalid_config_fails_closed() -> None:
    with pytest.raises(ValueError, match="thresholds"):
        VadGateConfig(enter_threshold=0.3, exit_threshold=0.5)  # exit > enter.
    with pytest.raises(ValueError, match="durations"):
        VadGateConfig(min_speech_s=-0.1)


def test_determinism_identical_script_identical_events() -> None:
    script = [0.0, 0.6, 0.7, 0.2, 0.9, 0.9, 0.9, 0.9, 0.9, 0.1] * 20
    reference = run_probs(machine_with(), list(script))
    for _ in range(20):
        assert run_probs(machine_with(), list(script)) == reference
