"""Boundary-exact tests for the sustained loopback-VAD ad-hoc call trigger.

Pins the fire threshold at EXACTLY N seconds of speech (>= semantics, with
N-epsilon staying silent), hysteresis (must drain below the re-arm level AND
outlast the cooldown), capture-running quiet, gap capping (unmeasured time is
never billed as speech), and fail-closed input validation.
"""

import pytest

from engine.detect.detection_signal_types import SOURCE_ADHOC_LOOPBACK, AdHocCallSuspected
from engine.detect.sustained_loopback_vad_trigger import (
    SustainedLoopbackVadConfig,
    SustainedLoopbackVadTrigger,
)

HOP = 0.5  # seconds between samples in these tests

CONFIG = SustainedLoopbackVadConfig(
    speech_prob_threshold=0.5,
    rolling_window_s=30.0,
    min_speech_s_in_window=12.0,
    rearm_below_speech_s=4.0,
    cooldown_s=120.0,
    max_sample_gap_s=1.0,
)


def feed_run(
    trigger: SustainedLoopbackVadTrigger,
    start_ts: float,
    end_ts: float,
    probability: float,
    capture_active: bool = False,
) -> list[tuple[float, AdHocCallSuspected]]:
    """Feed samples every HOP seconds over [start_ts, end_ts]; collect fires."""
    fires: list[tuple[float, AdHocCallSuspected]] = []
    steps = round((end_ts - start_ts) / HOP)
    for i in range(steps + 1):
        ts = start_ts + i * HOP
        event = trigger.feed(ts, probability, capture_active)
        if event is not None:
            fires.append((ts, event))
    return fires


def test_fires_exactly_at_threshold_not_before() -> None:
    trigger = SustainedLoopbackVadTrigger(CONFIG)
    # First sample accounts 0s, each later sample HOP: speech == ts.
    fires = feed_run(trigger, 0.0, 11.5, probability=0.9)
    assert fires == []  # 11.5s of speech: just under N -> silent
    assert trigger.speech_seconds_in_window == pytest.approx(11.5)
    event = trigger.feed(12.0, 0.9, capture_active=False)
    assert event is not None  # exactly N counts (>=), boundary-exact
    assert event.source == SOURCE_ADHOC_LOOPBACK
    assert event.speech_seconds_in_window == pytest.approx(12.0)
    assert event.rolling_window_s == 30.0
    assert 0.0 <= event.confidence <= 1.0


def test_n_minus_epsilon_then_silence_never_fires() -> None:
    trigger = SustainedLoopbackVadTrigger(CONFIG)
    assert feed_run(trigger, 0.0, 11.5, probability=0.9) == []
    assert feed_run(trigger, 12.0, 60.0, probability=0.0) == []
    assert trigger.speech_seconds_in_window == pytest.approx(0.0)  # fully drained


def test_probability_threshold_boundary_is_speech_at_equal() -> None:
    at_threshold = SustainedLoopbackVadTrigger(CONFIG)
    fires = feed_run(at_threshold, 0.0, 12.0, probability=0.5)  # p == threshold
    assert len(fires) == 1
    just_under = SustainedLoopbackVadTrigger(CONFIG)
    assert feed_run(just_under, 0.0, 60.0, probability=0.4999) == []


def test_one_long_call_fires_exactly_once_never_spams() -> None:
    """Continuous speech far past the cooldown: hysteresis blocks re-fire."""
    trigger = SustainedLoopbackVadTrigger(CONFIG)
    fires = feed_run(trigger, 0.0, 300.0, probability=0.9)  # 5 minutes of speech
    assert [ts for ts, _ in fires] == [12.0]


def test_rearm_requires_cooldown_and_drain_then_fires_again() -> None:
    trigger = SustainedLoopbackVadTrigger(CONFIG)
    assert len(feed_run(trigger, 0.0, 12.0, probability=0.9)) == 1  # fired at 12.0
    # Silence long past the window: speech drains to 0 well before t=132,
    # but the cooldown (fires+120 = 132) must ALSO elapse before re-arm.
    assert feed_run(trigger, 12.5, 135.0, probability=0.0) == []
    # Fresh sustained speech after re-arm accumulates and fires exactly once.
    fires = feed_run(trigger, 135.5, 160.0, probability=0.9)
    assert len(fires) == 1
    # Speech time accrues from the previous sample at 135.0, so 12s of
    # accounted speech completes at ts = 147.0.
    assert fires[0][0] == pytest.approx(147.0)


def test_cooldown_elapsed_but_not_drained_stays_silent() -> None:
    trigger = SustainedLoopbackVadTrigger(CONFIG)
    # Speech 0..12 fires; keep speaking until t=140 (> cooldown end at 132):
    # window still holds 30s >> rearm 4s, so it must NOT re-arm or re-fire.
    fires = feed_run(trigger, 0.0, 140.0, probability=0.9)
    assert [ts for ts, _ in fires] == [12.0]
    # Even a fresh silence-then-speech burst inside COOLDOWN can't fire until
    # the drain condition has actually been observed on a feed.
    assert trigger.feed(140.5, 0.9, capture_active=False) is None


def test_capture_active_keeps_trigger_quiet_but_state_updates() -> None:
    trigger = SustainedLoopbackVadTrigger(CONFIG)
    fires = feed_run(trigger, 0.0, 20.0, probability=0.9, capture_active=True)
    assert fires == []  # already capturing: never suggest an ad-hoc call
    # Capture stops mid-call: the accumulated window may now fire (once).
    event = trigger.feed(20.5, 0.9, capture_active=False)
    assert event is not None


def test_feed_gap_is_capped_never_billed_as_speech() -> None:
    trigger = SustainedLoopbackVadTrigger(CONFIG)
    trigger.feed(0.0, 0.9, False)
    # 20s gap between speech samples: only max_sample_gap_s (1.0) is counted.
    trigger.feed(20.0, 0.9, False)
    assert trigger.speech_seconds_in_window == pytest.approx(1.0)


def test_old_speech_evicts_from_rolling_window() -> None:
    trigger = SustainedLoopbackVadTrigger(CONFIG)
    feed_run(trigger, 0.0, 6.0, probability=0.9)  # 6s speech
    assert trigger.speech_seconds_in_window == pytest.approx(6.0)
    feed_run(trigger, 6.5, 40.0, probability=0.0)  # silence pushes it out
    assert trigger.speech_seconds_in_window == pytest.approx(0.0)


def test_reset_clears_all_rolling_state() -> None:
    trigger = SustainedLoopbackVadTrigger(CONFIG)
    feed_run(trigger, 0.0, 6.0, probability=0.9)
    trigger.reset()
    assert trigger.speech_seconds_in_window == 0.0
    # After reset, timestamps may restart from zero without a stream-order error.
    assert trigger.feed(0.0, 0.9, False) is None


# --- fail-closed input validation --------------------------------------------


@pytest.mark.parametrize("bad_probability", [float("nan"), -0.001, 1.001, 2.0])
def test_garbage_probability_raises(bad_probability: float) -> None:
    trigger = SustainedLoopbackVadTrigger(CONFIG)
    with pytest.raises(ValueError):
        trigger.feed(0.0, bad_probability, False)


def test_out_of_order_or_nan_timestamps_raise() -> None:
    trigger = SustainedLoopbackVadTrigger(CONFIG)
    trigger.feed(10.0, 0.9, False)
    with pytest.raises(ValueError):
        trigger.feed(9.5, 0.9, False)
    with pytest.raises(ValueError):
        trigger.feed(float("nan"), 0.9, False)


@pytest.mark.parametrize(
    "bad_config_kwargs",
    [
        {"speech_prob_threshold": 0.0},
        {"speech_prob_threshold": 1.0},
        {"rolling_window_s": 0.0},
        {"min_speech_s_in_window": 0.0},
        {"min_speech_s_in_window": 31.0},  # exceeds the rolling window
        {"rearm_below_speech_s": 12.0},  # rearm must sit BELOW the fire level
        {"rearm_below_speech_s": -1.0},
        {"cooldown_s": -0.1},
        {"max_sample_gap_s": 0.0},
    ],
)
def test_degenerate_configs_are_rejected(bad_config_kwargs: dict[str, float]) -> None:
    with pytest.raises(ValueError):
        SustainedLoopbackVadConfig(**bad_config_kwargs)
