"""Tests for rolling live summary service."""

from __future__ import annotations

import pytest

from engine.ask.live_summary_service import LiveSummaryService


class _FakeRouter:
    def __init__(self, text: str = "- Topic A\n- Topic B") -> None:
        self._text = text
        self.calls = 0
        self.kwargs: list[dict[str, object]] = []

    async def route(self, task_type: str, system_frame: str, messages, **kwargs):
        self.calls += 1
        self.kwargs.append(kwargs)

        class _Completion:
            text = self._text

        class _Routed:
            completion = _Completion()

        return _Routed()


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
