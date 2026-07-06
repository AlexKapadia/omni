"""Routing-table resolution tests: both keyed worlds, dedupe, deny-by-default.

The routing policy is data (claude.md: config-driven table); these tests pin
the EXACT resolved chain for every task type in BOTH worlds — the required
Groq+Gemini pair alone, and the world where the optional Anthropic key
exists and Claude is promoted — plus the fail-closed edges: unknown task
types refused, un-keyed providers never attempted, empty chains loud.
"""

import pytest

from engine.router.completion_contract import Provider, TaskType
from engine.router.router_errors import MisconfiguredRouteError, UnknownTaskTypeError
from engine.router.routing_table import (
    ANTHROPIC_MODEL,
    GEMINI_FLASH_MODEL,
    GEMINI_PRO_MODEL,
    GROQ_FAST_MODEL,
    ROUTING_TABLE,
    resolve_route,
)

# The two worlds that matter (session decision: Groq+Gemini required pair,
# Anthropic optional-promoted).
PAIR_WORLD = frozenset({"groq", "gemini"})
FULL_WORLD = frozenset({"groq", "gemini", "anthropic"})


def _chain(task_type: str, keyed: frozenset[str]) -> list[tuple[str, str]]:
    """Resolve and flatten to comparable (provider, model) pairs."""
    resolved = resolve_route(task_type, keyed)
    return [(slot.provider.value, slot.model) for slot in resolved.attempts]


# ---------------------------------------------------------------------------
# Table completeness and latency budgets
# ---------------------------------------------------------------------------


def test_every_task_type_has_exactly_one_routing_row() -> None:
    assert set(ROUTING_TABLE.keys()) == set(TaskType)


def test_live_paths_hold_the_1200ms_p95_budget_boundary_exact() -> None:
    """Live paths (extraction, intent) must budget p95 < 1.2 s — the table
    records exactly 1200 ms, and no live path may exceed it."""
    assert ROUTING_TABLE[TaskType.LIVE_EXTRACTION].latency_budget_p95_ms == 1200
    assert ROUTING_TABLE[TaskType.INTENT_PARSING].latency_budget_p95_ms == 1200


def test_every_row_has_a_positive_latency_budget() -> None:
    for task_type, spec in ROUTING_TABLE.items():
        assert spec.latency_budget_p95_ms > 0, task_type


def test_resolved_route_carries_the_tables_budget() -> None:
    resolved = resolve_route("long_context_bulk", PAIR_WORLD)
    assert resolved.latency_budget_p95_ms == (
        ROUTING_TABLE[TaskType.LONG_CONTEXT_BULK].latency_budget_p95_ms
    )


# ---------------------------------------------------------------------------
# The exact chains, pair world (Groq + Gemini only — the shipping default)
# ---------------------------------------------------------------------------


def test_live_extraction_pair_world_is_groq_then_gemini_flash() -> None:
    assert _chain("live_extraction", PAIR_WORLD) == [
        ("groq", GROQ_FAST_MODEL),
        ("gemini", GEMINI_FLASH_MODEL),
    ]


def test_intent_parsing_pair_world_falls_back_to_gemini_flash() -> None:
    assert _chain("intent_parsing", PAIR_WORLD) == [
        ("groq", GROQ_FAST_MODEL),
        ("gemini", GEMINI_FLASH_MODEL),
    ]


def test_enhanced_notes_pair_world_is_gemini_pro_then_flash() -> None:
    assert _chain("enhanced_notes", PAIR_WORLD) == [
        ("gemini", GEMINI_PRO_MODEL),
        ("gemini", GEMINI_FLASH_MODEL),
    ]


def test_ask_synthesis_pair_world_dedupes_the_flash_fallback() -> None:
    """Primary collapses to gemini-flash; the explicit flash fallback must
    dedupe rather than schedule the same model twice."""
    assert _chain("ask_synthesis", PAIR_WORLD) == [
        ("gemini", GEMINI_FLASH_MODEL),
        ("gemini", GEMINI_PRO_MODEL),
    ]


def test_long_context_bulk_pair_world_is_flash_then_pro() -> None:
    assert _chain("long_context_bulk", PAIR_WORLD) == [
        ("gemini", GEMINI_FLASH_MODEL),
        ("gemini", GEMINI_PRO_MODEL),
    ]


def test_agentic_tools_pair_world_runs_on_gemini_function_calling() -> None:
    assert _chain("agentic_tools", PAIR_WORLD) == [
        ("gemini", GEMINI_FLASH_MODEL),
        ("gemini", GEMINI_PRO_MODEL),
    ]


# ---------------------------------------------------------------------------
# The exact chains, full world (Anthropic keyed -> Claude promoted)
# ---------------------------------------------------------------------------


def test_live_extraction_full_world_is_unchanged_no_anthropic_slot() -> None:
    """live_extraction has no conditional slot: adding an Anthropic key must
    NOT perturb the live path (Groq speed is the point)."""
    assert _chain("live_extraction", FULL_WORLD) == _chain("live_extraction", PAIR_WORLD)


def test_intent_parsing_full_world_promotes_anthropic_as_fallback() -> None:
    assert _chain("intent_parsing", FULL_WORLD) == [
        ("groq", GROQ_FAST_MODEL),
        ("anthropic", ANTHROPIC_MODEL),
    ]


def test_enhanced_notes_full_world_promotes_anthropic_primary() -> None:
    assert _chain("enhanced_notes", FULL_WORLD) == [
        ("anthropic", ANTHROPIC_MODEL),
        ("gemini", GEMINI_FLASH_MODEL),
    ]


def test_ask_synthesis_full_world_promotes_anthropic_primary() -> None:
    assert _chain("ask_synthesis", FULL_WORLD) == [
        ("anthropic", ANTHROPIC_MODEL),
        ("gemini", GEMINI_FLASH_MODEL),
        ("gemini", GEMINI_PRO_MODEL),
    ]


def test_long_context_bulk_full_world_keeps_gemini_flash_primary() -> None:
    """Gemini stays primary for bulk long-context even when Claude is keyed
    (cost/context is the point); Anthropic becomes the fallback."""
    assert _chain("long_context_bulk", FULL_WORLD) == [
        ("gemini", GEMINI_FLASH_MODEL),
        ("anthropic", ANTHROPIC_MODEL),
    ]


def test_agentic_tools_full_world_promotes_anthropic_primary() -> None:
    assert _chain("agentic_tools", FULL_WORLD) == [
        ("anthropic", ANTHROPIC_MODEL),
        ("gemini", GEMINI_FLASH_MODEL),
        ("gemini", GEMINI_PRO_MODEL),
    ]


# ---------------------------------------------------------------------------
# Deny-by-default and fail-closed edges
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "bad_task",
    [
        "",
        "unknown_task",
        "Live_Extraction",  # case matters: no fuzzy matching on a deny list
        "live_extraction ",  # trailing whitespace is NOT normalised away
        "live-extraction",
        "drop table; --",
        "ask_synthesis\x00",
    ],
)
def test_unknown_task_types_are_refused(bad_task: str) -> None:
    with pytest.raises(UnknownTaskTypeError):
        resolve_route(bad_task, FULL_WORLD)


def test_unkeyed_providers_are_dropped_from_the_chain() -> None:
    """A provider without a key can only auth-fail — it must never be
    attempted at all (fail closed, no wasted live-path latency)."""
    assert _chain("live_extraction", frozenset({"gemini"})) == [
        ("gemini", GEMINI_FLASH_MODEL)
    ]


def test_no_keyed_providers_raises_misconfigured_not_empty_chain() -> None:
    with pytest.raises(MisconfiguredRouteError):
        resolve_route("live_extraction", frozenset())


def test_anthropic_only_world_cannot_serve_the_live_path() -> None:
    """Adversarial: only Anthropic keyed. live_extraction's chain contains
    no Anthropic slot, so resolution must refuse loudly — not invent one."""
    with pytest.raises(MisconfiguredRouteError):
        resolve_route("live_extraction", frozenset({"anthropic"}))


def test_anthropic_only_world_still_serves_anthropic_capable_tasks() -> None:
    assert _chain("enhanced_notes", frozenset({"anthropic"})) == [
        ("anthropic", ANTHROPIC_MODEL)
    ]


def test_no_chain_ever_contains_an_unkeyed_provider_or_duplicates() -> None:
    """Property over the whole table x several worlds: every resolved chain
    is duplicate-free and only ever names keyed providers."""
    worlds = [
        PAIR_WORLD,
        FULL_WORLD,
        frozenset({"gemini"}),
        frozenset({"gemini", "anthropic"}),
    ]
    for world in worlds:
        for task_type in TaskType:
            try:
                resolved = resolve_route(task_type.value, world)
            except MisconfiguredRouteError:
                continue  # an empty chain refused loudly is correct
            pairs = [(s.provider.value, s.model) for s in resolved.attempts]
            assert len(pairs) == len(set(pairs)), (task_type, world)
            assert all(provider in world for provider, _ in pairs), (task_type, world)


def test_pair_world_serves_every_task_type() -> None:
    """The shipping default (no Anthropic key) must leave NO task unroutable."""
    for task_type in TaskType:
        resolved = resolve_route(task_type.value, PAIR_WORLD)
        assert len(resolved.attempts) >= 1
        assert Provider.ANTHROPIC not in {s.provider for s in resolved.attempts}
