"""selection_translate_service must not read a non-existent RouteSpec.max_tokens."""

from __future__ import annotations

import pytest

from engine.router.completion_contract import ChatMessage, Provider, ProviderCompletion, TaskType
from engine.router.routing_table import ROUTING_TABLE
from engine.translate.selection_translate_service import translate_selection


def test_live_extraction_route_spec_has_no_max_tokens_attribute() -> None:
    """Pin the bug: RouteSpec has no max_tokens — reading it AttributeErrors."""
    spec = ROUTING_TABLE[TaskType.LIVE_EXTRACTION]
    assert not hasattr(spec, "max_tokens")


@pytest.mark.asyncio
async def test_translate_selection_uses_literal_max_tokens_not_route_spec() -> None:
    """Calling translate_selection must not AttributeError on RouteSpec.max_tokens."""
    calls: list[dict[str, object]] = []

    async def fake_route(
        task_type: str,
        system_frame: str,
        messages: tuple[ChatMessage, ...],
        *,
        max_tokens: int = 4096,
        preferred_model: str | None = None,
        preferred_provider: str | None = None,
        **_kwargs: object,
    ) -> object:
        calls.append(
            {
                "task_type": task_type,
                "max_tokens": max_tokens,
                "preferred_model": preferred_model,
                "preferred_provider": preferred_provider,
                "messages": messages,
            }
        )

        class _Routed:
            completion = ProviderCompletion(
                text="hola",
                provider=Provider.OLLAMA,
                model="llama3.2",
                prompt_tokens=1,
                completion_tokens=1,
            )

        return _Routed()

    result = await translate_selection(
        fake_route,
        "hello",
        "Spanish",
        preferred_model="llama3.2",
        preferred_provider="ollama",
    )
    assert result == "hola"
    assert len(calls) == 1
    assert calls[0]["max_tokens"] == 2048
    assert calls[0]["task_type"] in {
        TaskType.ASK_SYNTHESIS.value,
        TaskType.ENHANCED_NOTES.value,
    }
    assert calls[0]["preferred_provider"] == "ollama"
    assert calls[0]["preferred_model"] == "llama3.2"
