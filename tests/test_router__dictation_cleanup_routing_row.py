"""Routing row for task ``dictation_cleanup``: chain + budget, both worlds.

The cleanup call sits INSIDE the release->text dictation path, so its row
is the tightest in the table: Groq primary -> Gemini Flash fallback with
an 800 ms per-attempt budget. Pinned exactly, in both keyed worlds — and
proven additive (no existing row changed).
"""

from engine.router.completion_contract import Provider, TaskType
from engine.router.routing_table import (
    GEMINI_FLASH_MODEL,
    GROQ_FAST_MODEL,
    ROUTING_TABLE,
    resolve_route,
)

PAIR_WORLD = frozenset({"groq", "gemini"})
FULL_WORLD = frozenset({"groq", "gemini", "anthropic"})


def _chain(keyed: frozenset[str]) -> list[tuple[str, str]]:
    resolved = resolve_route("dictation_cleanup", keyed)
    return [(slot.provider.value, slot.model) for slot in resolved.attempts]


def test_pair_world_chain_is_groq_then_gemini_flash() -> None:
    assert _chain(PAIR_WORLD) == [
        ("groq", GROQ_FAST_MODEL),
        ("gemini", GEMINI_FLASH_MODEL),
    ]


def test_anthropic_key_does_not_perturb_the_cleanup_chain() -> None:
    """Cleanup has no conditional slot: speed is the point, Claude never
    enters this path even when keyed."""
    assert _chain(FULL_WORLD) == _chain(PAIR_WORLD)
    assert all(provider != Provider.ANTHROPIC.value for provider, _ in _chain(FULL_WORLD))


def test_budget_is_exactly_800ms_the_tightest_row() -> None:
    """Boundary-exact: 800 ms per attempt keeps cleanup inside the <1.2 s
    release->text budget, and no other row is tighter (cleanup must stay
    the most latency-paranoid task in the table)."""
    spec = ROUTING_TABLE[TaskType.DICTATION_CLEANUP]
    assert spec.latency_budget_p95_ms == 800
    assert spec.latency_budget_p95_ms == min(
        row.latency_budget_p95_ms for row in ROUTING_TABLE.values()
    )


def test_resolved_route_carries_the_800ms_budget() -> None:
    resolved = resolve_route("dictation_cleanup", PAIR_WORLD)
    assert resolved.latency_budget_p95_ms == 800


def test_groq_only_world_still_serves_cleanup() -> None:
    assert _chain(frozenset({"groq"})) == [("groq", GROQ_FAST_MODEL)]


def test_gemini_only_world_still_serves_cleanup() -> None:
    # Groq un-keyed -> dropped (fail closed); the fallback carries the task.
    assert _chain(frozenset({"gemini"})) == [("gemini", GEMINI_FLASH_MODEL)]
