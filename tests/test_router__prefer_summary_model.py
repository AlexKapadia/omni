"""Preferred summary model reorders the enhance/ask chain when keyed."""

from __future__ import annotations

from engine.router.completion_contract import Provider, TaskType
from engine.router.routing_table import prefer_summary_model, resolve_route


def test_prefer_gemini_flash_moves_it_first_when_keyed() -> None:
    keyed = frozenset({"gemini", "anthropic"})
    base = resolve_route(TaskType.ENHANCED_NOTES.value, keyed)
    preferred = prefer_summary_model(base, "gemini-2.5-flash", keyed)
    assert preferred.attempts[0].provider == Provider.GEMINI
    assert preferred.attempts[0].model == "gemini-2.5-flash"


def test_prefer_unknown_model_leaves_chain_unchanged() -> None:
    keyed = frozenset({"gemini"})
    base = resolve_route(TaskType.ENHANCED_NOTES.value, keyed)
    preferred = prefer_summary_model(base, "totally-fake-model", keyed)
    assert preferred.attempts == base.attempts


def test_prefer_unkeyed_provider_does_not_inject_slot() -> None:
    keyed = frozenset({"gemini"})
    base = resolve_route(TaskType.ENHANCED_NOTES.value, keyed)
    preferred = prefer_summary_model(base, "claude-sonnet-4-5", keyed)
    assert all(a.provider != Provider.ANTHROPIC for a in preferred.attempts)


def test_prefer_openai_prepends_when_openai_keyed_for_ask() -> None:
    keyed = frozenset({"gemini", "openai"})
    base = resolve_route(TaskType.ASK_SYNTHESIS.value, keyed)
    preferred = prefer_summary_model(base, "gpt-4o", keyed)
    assert preferred.attempts[0].provider == Provider.OPENAI
    assert preferred.attempts[0].model == "gpt-4o"


def test_prefer_openai_injects_into_enhanced_notes_when_keyed() -> None:
    keyed = frozenset({"gemini", "openai"})
    base = resolve_route(TaskType.ENHANCED_NOTES.value, keyed)
    preferred = prefer_summary_model(base, "gpt-4o", keyed)
    assert preferred.attempts[0].provider == Provider.OPENAI
    assert preferred.attempts[0].model == "gpt-4o"
