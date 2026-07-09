"""Translate selected text via the router (selection translation hotkey)."""

from __future__ import annotations

from engine.router.completion_contract import ChatMessage, TaskType
from engine.router.routing_table import ROUTING_TABLE

_TRANSLATION_SYSTEM = (
    "Translate the user's selected text accurately. Preserve tone and formatting. "
    "Return only the translation with no preamble."
)


async def translate_selection(route, text: str, target_lang: str) -> str:
    trimmed = text.strip()
    if not trimmed:
        raise ValueError("No text selected to translate")
    lang = target_lang.strip() or "English"
    user = f"Target language: {lang}\n\nText:\n{trimmed}"
    routed = await route(
        TaskType.LIVE_EXTRACTION.value,
        _TRANSLATION_SYSTEM,
        (ChatMessage(role="user", content=user),),
        max_tokens=ROUTING_TABLE[TaskType.LIVE_EXTRACTION].max_tokens,
    )
    translated = routed.completion.text.strip()
    if not translated:
        raise ValueError("Translation returned empty text")
    return translated
