"""Per-turn latency breakdown: the speed showcase, exact to the millisecond.

Purpose: Omni surfaces real performance live (user speed mandate), and
Naomi's headline number is end-of-speech → first audible audio. This module
holds the four measured spans of one turn and derives the total BY
CONSTRUCTION as their sum, so the displayed ``total_ms`` can never disagree
with its parts (§3.11: zero numerical errors on deterministic paths — the
"why" must match the "what" exactly). Every value is integer milliseconds:
the wall clock is measured in seconds and rounded ONCE at construction, so
the arithmetic that follows is exact integer addition, not float drift.
Pipeline position: assembled by ``engine.naomi.naomi_turn_orchestrator`` from
the stage clocks and broadcast as ``naomi.turn.latency``.

Budget (docs/design/naomi-visual-brief.md §7): p50 total ≈ 620ms, p95 ≈ 1s.
This module records reality; it never clamps to the budget.
"""

from dataclasses import dataclass


def _reject_negative(name: str, value: int) -> int:
    """A latency span is never negative — a negative value is a clock bug.

    Fail closed on nonsense rather than broadcasting an impossible number.
    """
    if value < 0:
        raise ValueError(f"{name} must be >= 0 ms, got {value}")
    return value


@dataclass(frozen=True)
class NaomiTurnLatency:
    """The four spans of one turn; ``total_ms`` is their exact sum.

    - ``endpoint_ms``  — user stops speaking → VAD declares end-of-speech.
    - ``retrieval_ms`` — live-tier structured-first + hybrid RRF retrieval.
    - ``llm_ms``       — router synthesis (whole answer; no streaming router).
    - ``ttfa_ms``      — reply dispatched → FIRST audio chunk from Cartesia.
    All are non-negative integer milliseconds (validated at construction).
    """

    endpoint_ms: int
    retrieval_ms: int
    llm_ms: int
    ttfa_ms: int

    def __post_init__(self) -> None:
        _reject_negative("endpoint_ms", self.endpoint_ms)
        _reject_negative("retrieval_ms", self.retrieval_ms)
        _reject_negative("llm_ms", self.llm_ms)
        _reject_negative("ttfa_ms", self.ttfa_ms)

    @property
    def total_ms(self) -> int:
        """The turn total — exact integer sum of the four spans, never stored
        separately, so it cannot drift from its parts."""
        return self.endpoint_ms + self.retrieval_ms + self.llm_ms + self.ttfa_ms

    def as_event_payload(self, turn_id: str) -> dict[str, object]:
        """The ``naomi.turn.latency`` wire shape (§7 speed showcase)."""
        return {
            "turn_id": turn_id,
            "endpoint_ms": self.endpoint_ms,
            "retrieval_ms": self.retrieval_ms,
            "llm_ms": self.llm_ms,
            "ttfa_ms": self.ttfa_ms,
            "total_ms": self.total_ms,
        }


def milliseconds_between(start_s: float, end_s: float) -> int:
    """Convert a monotonic-second span to non-negative integer milliseconds.

    Rounds ONCE (banker's rounding via ``round``) at the boundary between the
    float clock and the integer latency arithmetic, and floors at 0 so a
    sub-millisecond clock jitter (end marginally before start) reads 0, never
    a negative span.
    """
    return max(0, round((end_s - start_s) * 1000))
