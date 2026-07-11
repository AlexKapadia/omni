"""LiveTranslationService: mid-session lang hot-reload + RouterError visibility."""

from __future__ import annotations

import logging
from typing import Any

import pytest

from engine.ask.live_translation_service import LiveTranslationService
from engine.router.router_errors import RouterError


class _ScriptedRouter:
    def __init__(self, outcomes: list[Any]) -> None:
        self.outcomes = list(outcomes)
        self.calls: list[dict[str, Any]] = []

    async def route(self, task_type: str, system_frame: str, messages: tuple, **kwargs):
        self.calls.append({"task_type": task_type, "system_frame": system_frame, "kwargs": kwargs})
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome

        class _Routed:
            class completion:
                text = outcome

        return _Routed()


@pytest.mark.asyncio
async def test_set_target_lang_hot_reloads_system_frame() -> None:
    emitted: list[list[dict[str, object]]] = []

    async def emit(lines: list[dict[str, object]]) -> None:
        emitted.append(lines)

    router = _ScriptedRouter(["Them: bonjour"])
    clock = {"t": 0.0}

    def now() -> float:
        return clock["t"]

    svc = LiveTranslationService(router, emit, "Spanish", cadence_seconds=1.0, clock=now)
    clock["t"] = 2.0
    svc.set_target_lang("French")
    await svc.on_final_segment("them", "hello")
    assert "French" in router.calls[0]["system_frame"]
    assert "Spanish" not in router.calls[0]["system_frame"]
    assert emitted


@pytest.mark.asyncio
async def test_router_error_logs_warning_instead_of_silent_return(
    caplog: pytest.LogCaptureFixture,
) -> None:
    async def emit(_lines: list[dict[str, object]]) -> None:
        raise AssertionError("must not emit on RouterError")

    router = _ScriptedRouter([RouterError("every provider failed")])
    clock = {"t": 0.0}
    svc = LiveTranslationService(
        router, emit, "Spanish", cadence_seconds=1.0, clock=lambda: clock["t"]
    )
    clock["t"] = 2.0
    with caplog.at_level(logging.WARNING, logger="engine.ask.live_translation_service"):
        await svc.on_final_segment("them", "hello")
    assert any("translation" in r.message.lower() for r in caplog.records)
