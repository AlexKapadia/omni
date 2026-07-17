"""Tests for rolling live summary service."""

from __future__ import annotations

import pytest

from engine.ask.live_summary_service import LiveSummaryService
from engine.router.completion_contract import (
    ChatMessage,
    Provider,
    ProviderCompletion,
    RoutedCompletion,
    ToolSpec,
)


class _FakeRouter:
    def __init__(self, text: str = "- Topic A\n- Topic B") -> None:
        self._text = text
        self.calls = 0
        self.kwargs: list[dict[str, object]] = []

    async def route(
        self,
        task_type: str,
        system_frame: str,
        messages: tuple[ChatMessage, ...],
        *,
        tools: tuple[ToolSpec, ...] = (),
        json_schema: dict[str, object] | None = None,
        max_tokens: int = 4096,
        preferred_model: str | None = None,
        preferred_provider: str | None = None,
    ) -> RoutedCompletion:
        self.calls += 1
        self.kwargs.append(
            {
                "tools": tools,
                "json_schema": json_schema,
                "max_tokens": max_tokens,
                "preferred_model": preferred_model,
                "preferred_provider": preferred_provider,
            }
        )
        return RoutedCompletion(
            completion=ProviderCompletion(
                text=self._text,
                provider=Provider.GROQ,
                model="stub",
                prompt_tokens=1,
                completion_tokens=1,
            ),
            provider=Provider.GROQ,
            model="stub",
            latency_ms=1,
        )


@pytest.mark.asyncio
async def test_live_summary_emits_on_cadence() -> None:
    emitted: list[tuple[str, int]] = []

    async def emit(summary: str, updated_at_ms: int) -> None:
        emitted.append((summary, updated_at_ms))

    router = _FakeRouter()
    clock = {"t": 0.0}

    def now() -> float:
        return clock["t"]

    service = LiveSummaryService(router, emit, cadence_seconds=60.0, clock=now)
    await service.on_final_segment("them", "Hello everyone")
    assert emitted == []
    clock["t"] = 61.0
    await service.on_final_segment("me", "Hi there")
    assert len(emitted) == 1
    assert "Topic A" in emitted[0][0]


@pytest.mark.asyncio
async def test_live_summary_passes_preferred_summary_settings() -> None:
    async def emit(_summary: str, _updated_at_ms: int) -> None:
        return None

    router = _FakeRouter()
    clock = {"t": 0.0}

    def now() -> float:
        return clock["t"]

    service = LiveSummaryService(
        router,
        emit,
        cadence_seconds=1.0,
        clock=now,
        preferred_model="llama3.2",
        preferred_provider="ollama",
    )
    clock["t"] = 2.0
    await service.on_final_segment("them", "Hello")
    assert router.calls == 1
    assert router.kwargs[0]["preferred_model"] == "llama3.2"
    assert router.kwargs[0]["preferred_provider"] == "ollama"
