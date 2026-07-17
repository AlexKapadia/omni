"""Translate selected text via the router (selection translation hotkey / Settings)."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from engine.router.completion_contract import ChatMessage, TaskType

# Literal budget — RouteSpec has no max_tokens attribute (AttributeError if read).
SELECTION_TRANSLATE_MAX_TOKENS = 2048

_TRANSLATION_SYSTEM = (
    "Translate the user's selected text accurately. Preserve tone and formatting. "
    "Return only the translation with no preamble."
)

RouteFn = Callable[..., Awaitable[Any]]


async def translate_selection(
    route: RouteFn,
    text: str,
    target_lang: str,
    *,
    preferred_model: str | None = None,
    preferred_provider: str | None = None,
) -> str:
    """Translate ``text`` into ``target_lang`` via ask_synthesis + summary prefer."""
    trimmed = text.strip()
    if not trimmed:
        raise ValueError("No text selected to translate")
    lang = target_lang.strip() or "English"
    user = f"Target language: {lang}\n\nText:\n{trimmed}"
    # ask_synthesis (not live_extraction): quality path + Ollama in default chain;
    # preferred_* still prepends when Settings picks a summary provider.
    routed = await route(
        TaskType.ASK_SYNTHESIS.value,
        _TRANSLATION_SYSTEM,
        (ChatMessage(role="user", content=user),),
        max_tokens=SELECTION_TRANSLATE_MAX_TOKENS,
        preferred_model=preferred_model,
        preferred_provider=preferred_provider,
    )
    translated = str(routed.completion.text).strip()
    if not translated:
        raise ValueError("Translation returned empty text")
    return translated
