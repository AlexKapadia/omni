"""Enrichment wiring hot-reloads live_translation_lang mid-session."""

from __future__ import annotations

from pathlib import Path
from typing import cast

import pytest

from engine.ask.live_translation_service import LiveTranslationService
from engine.protocol import EventBroadcastHub
from engine.router import ProviderRouter
from engine.router.completion_contract import (
    ChatMessage,
    RoutedCompletion,
    ToolSpec,
)
from engine.storage.app_settings_repository import SETTING_LIVE_TRANSLATION_LANG
from engine.wiring.combined_enrichment_session import CombinedEnrichmentSession
from engine.wiring.live_meeting_enrichment_wiring import LiveMeetingEnrichmentWiring


class _Router:
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
        raise AssertionError("not used")


class _Summary:
    async def on_final_segment(self, stream: str, text: str) -> None:
        return None

    async def tick(self) -> None:
        return None

    async def flush(self) -> None:
        return None


class _Vault:
    async def on_final_segment(self, stream: str, text: str) -> None:
        return None

    async def tick(self) -> None:
        return None

    async def flush(self) -> None:
        return None


@pytest.mark.asyncio
async def test_apply_translation_lang_updates_active_service(tmp_path: Path) -> None:
    hub = EventBroadcastHub()
    wiring = LiveMeetingEnrichmentWiring(hub, db_path=tmp_path / "t.db", migrations_dir=tmp_path)

    async def emit(lines: list[dict[str, object]]) -> None:
        return None

    svc = LiveTranslationService(_Router(), emit, "Spanish")
    wiring._translation = svc
    wiring.apply_translation_lang({SETTING_LIVE_TRANSLATION_LANG: "French"})
    assert svc._target_lang == "French"


@pytest.mark.asyncio
async def test_apply_translation_lang_late_attaches_when_started_empty(
    tmp_path: Path,
) -> None:
    """Session started with empty lang must construct translation on enable."""
    hub = EventBroadcastHub()
    wiring = LiveMeetingEnrichmentWiring(hub, db_path=tmp_path / "t.db", migrations_dir=tmp_path)

    async def emit(lines: list[dict[str, object]]) -> None:
        return None

    router = _Router()
    combined = CombinedEnrichmentSession(_Summary(), _Vault(), translation=None)  # type: ignore[arg-type]
    wiring._session_router = cast(ProviderRouter, router)
    wiring._session_emit_translation = emit
    wiring._session_preferred_model = None
    wiring._session_preferred_provider = None
    wiring._combined = combined
    # Leave wiring._translation at its default None — assigning None here
    # would make mypy narrow the attribute to always-None for the rest of
    # this function (unreachable after the non-None assert).

    wiring.apply_translation_lang({SETTING_LIVE_TRANSLATION_LANG: "German"})

    translation = wiring._translation
    assert translation is not None
    assert translation._target_lang == "German"
    assert combined._translation is translation
