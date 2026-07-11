"""``preferred_provider`` (the ``summary_provider`` setting) reorders the
enhance/ask chain when its mapped provider is keyed — independent of and
composable with the existing ``preferred_model`` preference."""

from __future__ import annotations

from engine.router.completion_contract import Provider, TaskType
from engine.router.routing_table import prefer_summary_model, resolve_route


def test_prefer_provider_ollama_prepends_default_model_when_keyed() -> None:
    keyed = frozenset({"gemini", "ollama"})
    base = resolve_route(TaskType.ENHANCED_NOTES.value, keyed)
    preferred = prefer_summary_model(base, None, keyed, preferred_provider="ollama")
    assert preferred.attempts[0].provider == Provider.OLLAMA
    assert preferred.attempts[0].model == "llama3.2"


def test_prefer_provider_builtin_ai_maps_to_ollama() -> None:
    keyed = frozenset({"gemini", "ollama"})
    base = resolve_route(TaskType.ASK_SYNTHESIS.value, keyed)
    preferred = prefer_summary_model(base, None, keyed, preferred_provider="builtin-ai")
    assert preferred.attempts[0].provider == Provider.OLLAMA
    assert preferred.attempts[0].model == "llama3.2"


def test_prefer_provider_uses_preferred_model_over_provider_default() -> None:
    keyed = frozenset({"gemini", "ollama"})
    base = resolve_route(TaskType.ENHANCED_NOTES.value, keyed)
    preferred = prefer_summary_model(
        base, "gemma3:1b", keyed, preferred_provider="ollama"
    )
    assert preferred.attempts[0].provider == Provider.OLLAMA
    assert preferred.attempts[0].model == "gemma3:1b"


def test_prefer_provider_gemini_prepends_flash_default() -> None:
    keyed = frozenset({"gemini"})
    base = resolve_route(TaskType.ENHANCED_NOTES.value, keyed)
    preferred = prefer_summary_model(base, None, keyed, preferred_provider="gemini")
    assert preferred.attempts[0].provider == Provider.GEMINI
    assert preferred.attempts[0].model == "gemini-2.5-flash"


def test_prefer_provider_anthropic_prepends_claude_default_when_keyed() -> None:
    keyed = frozenset({"gemini", "anthropic"})
    base = resolve_route(TaskType.ASK_SYNTHESIS.value, keyed)
    preferred = prefer_summary_model(base, None, keyed, preferred_provider="anthropic")
    assert preferred.attempts[0].provider == Provider.ANTHROPIC
    assert preferred.attempts[0].model == "claude-sonnet-4-5"


def test_prefer_provider_openai_prepends_gpt4o_default_when_keyed() -> None:
    keyed = frozenset({"gemini", "openai"})
    base = resolve_route(TaskType.ENHANCED_NOTES.value, keyed)
    preferred = prefer_summary_model(base, None, keyed, preferred_provider="openai")
    assert preferred.attempts[0].provider == Provider.OPENAI
    assert preferred.attempts[0].model == "gpt-4o"


def test_prefer_provider_unkeyed_falls_through_to_model_logic() -> None:
    """A provider preference with no key must never invent an unkeyed call —
    it falls through to the (also unkeyed here) model-id logic unchanged."""
    keyed = frozenset({"gemini"})
    base = resolve_route(TaskType.ENHANCED_NOTES.value, keyed)
    preferred = prefer_summary_model(base, None, keyed, preferred_provider="anthropic")
    assert preferred.attempts == base.attempts
    assert all(a.provider != Provider.ANTHROPIC for a in preferred.attempts)


def test_prefer_provider_unknown_string_falls_through() -> None:
    keyed = frozenset({"gemini"})
    base = resolve_route(TaskType.ENHANCED_NOTES.value, keyed)
    preferred = prefer_summary_model(base, None, keyed, preferred_provider="totally-unknown")
    assert preferred.attempts == base.attempts


def test_prefer_provider_empty_string_is_treated_as_absent() -> None:
    keyed = frozenset({"gemini"})
    base = resolve_route(TaskType.ENHANCED_NOTES.value, keyed)
    preferred = prefer_summary_model(base, None, keyed, preferred_provider="   ")
    assert preferred.attempts == base.attempts


def test_prefer_provider_case_insensitive_match() -> None:
    keyed = frozenset({"gemini", "ollama"})
    base = resolve_route(TaskType.ENHANCED_NOTES.value, keyed)
    preferred = prefer_summary_model(base, None, keyed, preferred_provider="OLLAMA")
    assert preferred.attempts[0].provider == Provider.OLLAMA


def test_prefer_provider_wins_and_carries_its_own_model_preference() -> None:
    """Provider preference takes precedence per the settled decision; a
    model preference given alongside it names THAT provider's model (the
    Settings UI scopes the model dropdown to the chosen provider)."""
    keyed = frozenset({"gemini", "openai"})
    base = resolve_route(TaskType.ENHANCED_NOTES.value, keyed)
    preferred = prefer_summary_model(
        base, "gpt-4o-mini", keyed, preferred_provider="openai"
    )
    assert preferred.attempts[0].provider == Provider.OPENAI
    assert preferred.attempts[0].model == "gpt-4o-mini"


def test_prefer_provider_none_leaves_model_id_logic_authoritative() -> None:
    keyed = frozenset({"gemini", "anthropic"})
    base = resolve_route(TaskType.ENHANCED_NOTES.value, keyed)
    preferred = prefer_summary_model(base, "claude-sonnet-4-5", keyed, preferred_provider=None)
    assert preferred.attempts[0].provider == Provider.ANTHROPIC
