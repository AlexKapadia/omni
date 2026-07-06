"""Latency tracker: exact nearest-rank percentiles, bounds, rejection.

The lag numbers are a user-facing showcase — every reported percentile
must be a REAL observed value, exact to the unit (zero-numerical-error
rule), so the math is pinned against hand-computed cases.
"""

import pytest

from engine.stt.transcription_latency_tracker import TranscriptionLatencyTracker


def tracker_with(values: list[float]) -> TranscriptionLatencyTracker:
    tracker = TranscriptionLatencyTracker()
    for value in values:
        tracker.record(value)
    return tracker


def test_empty_tracker_reports_none_not_zero() -> None:
    tracker = TranscriptionLatencyTracker()
    assert tracker.percentile_ms(50) is None  # Honest: no data is not "0 ms".
    tracker.log_summary()  # Must not raise on empty.


def test_single_value_is_every_percentile() -> None:
    tracker = tracker_with([420.0])
    assert tracker.percentile_ms(50) == 420.0
    assert tracker.percentile_ms(95) == 420.0
    assert tracker.percentile_ms(100) == 420.0


def test_nearest_rank_percentiles_hand_computed_ten_values() -> None:
    """Values 100..1000: nearest-rank p50 = 5th value = 500, p95 = 10th = 1000."""
    tracker = tracker_with([float(v) for v in range(100, 1100, 100)])
    assert tracker.percentile_ms(50) == 500.0
    assert tracker.percentile_ms(95) == 1000.0
    assert tracker.percentile_ms(10) == 100.0
    assert tracker.percentile_ms(100) == 1000.0


def test_percentile_is_always_an_observed_value_never_interpolated() -> None:
    values = [3.0, 977.0, 41.0, 500.5, 12.25]
    tracker = tracker_with(values)
    for percentile in (1, 25, 50, 75, 95, 99, 100):
        result = tracker.percentile_ms(percentile)
        assert result in values, f"p{percentile}={result} was fabricated"


def test_insertion_order_does_not_change_percentiles() -> None:
    import random

    values = [float(v) for v in range(1, 101)]
    shuffled = list(values)
    random.Random(42).shuffle(shuffled)
    assert tracker_with(values).percentile_ms(95) == tracker_with(shuffled).percentile_ms(95)
    assert tracker_with(shuffled).percentile_ms(95) == 95.0  # Exact nearest-rank.


def test_rolling_window_keeps_only_the_newest_512_but_counts_all() -> None:
    tracker = TranscriptionLatencyTracker()
    for i in range(1000):
        tracker.record(float(i))
    assert tracker.recorded_total == 1000
    # Window holds 488..999; nearest-rank p50 over 512 values = 256th = 743.
    assert tracker.percentile_ms(50) == 743.0


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), -1.0, -0.001])
def test_garbage_lag_values_fail_closed(bad: float) -> None:
    tracker = TranscriptionLatencyTracker()
    with pytest.raises(ValueError, match="lag_ms"):
        tracker.record(bad)


def test_zero_lag_is_legal_boundary() -> None:
    tracker = tracker_with([0.0])
    assert tracker.percentile_ms(50) == 0.0


@pytest.mark.parametrize("bad_percentile", [0, -5, 101, 100.001])
def test_out_of_range_percentile_requests_fail_closed(bad_percentile: float) -> None:
    tracker = tracker_with([1.0])
    with pytest.raises(ValueError, match="percentile"):
        tracker.percentile_ms(bad_percentile)
