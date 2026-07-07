"""Naomi turn latency: exact integer arithmetic, boundary-precise conversion.

Adversarial intent: the speed showcase is a deterministic path, so a SINGLE
arithmetic error is unacceptable (§3.11). A seeded fuzz over the full span
domain asserts the total is ALWAYS the exact sum of its parts, never
float-drifted; the ms conversion rounds once and floors at zero; negatives
are rejected. Seeded RNG keeps it reproducible (no network, no hypothesis dep).
"""

import random

import pytest

from engine.naomi.naomi_turn_latency_breakdown import NaomiTurnLatency, milliseconds_between


def test_total_is_exact_sum_over_seeded_fuzz() -> None:
    rng = random.Random(20260707)
    for _ in range(5000):
        endpoint, retrieval, llm, ttfa = (rng.randint(0, 10_000_000) for _ in range(4))
        latency = NaomiTurnLatency(endpoint, retrieval, llm, ttfa)
        assert latency.total_ms == endpoint + retrieval + llm + ttfa
        payload = latency.as_event_payload("turn-x")
        # The wire total must equal the composed total — "why" matches "what".
        assert payload["total_ms"] == latency.total_ms
        assert payload["endpoint_ms"] == endpoint and payload["ttfa_ms"] == ttfa
        assert payload["turn_id"] == "turn-x"


@pytest.mark.parametrize(
    ("endpoint", "retrieval", "llm", "ttfa", "expected"),
    [
        (200, 15, 280, 70, 565),
        (0, 0, 0, 0, 0),
        (700, 40, 420, 130, 1290),
    ],
)
def test_representative_totals(
    endpoint: int, retrieval: int, llm: int, ttfa: int, expected: int
) -> None:
    assert NaomiTurnLatency(endpoint, retrieval, llm, ttfa).total_ms == expected


@pytest.mark.parametrize("field_index", range(4))
def test_negative_span_is_rejected(field_index: int) -> None:
    spans = [10, 10, 10, 10]
    spans[field_index] = -1
    with pytest.raises(ValueError, match="must be >= 0"):
        NaomiTurnLatency(*spans)


def test_milliseconds_between_rounds_once_and_floors_at_zero() -> None:
    assert milliseconds_between(1.0, 1.7005) == 700  # 700.5ms rounds to 700 (banker's)
    assert milliseconds_between(1.0, 1.7006) == 701  # 700.6ms rounds to 701
    # Sub-millisecond jitter (end marginally before start) never goes negative.
    assert milliseconds_between(5.0, 4.9999) == 0
    assert milliseconds_between(5.0, 5.0) == 0


def test_milliseconds_between_never_negative_over_seeded_fuzz() -> None:
    rng = random.Random(11)
    for _ in range(2000):
        start = rng.uniform(0, 1e6)
        delta = rng.uniform(0, 1e3)
        assert milliseconds_between(start, start + delta) >= 0
        assert milliseconds_between(start + delta, start) >= 0  # reversed → floored 0
