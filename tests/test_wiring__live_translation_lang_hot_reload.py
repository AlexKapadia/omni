"""Enrichment wiring hot-reloads live_translation_lang mid-session."""

from __future__ import annotations

from pathlib import Path

import pytest

from engine.ask.live_translation_service import LiveTranslationService
from engine.protocol import EventBroadcastHub
from engine.storage.app_settings_repository import SETTING_LIVE_TRANSLATION_LANG
from engine.wiring.combined_enrichment_session import CombinedEnrichmentSession
from engine.wiring.live_meeting_enrichment_wiring import LiveMeetingEnrichmentWiring


class _Router:
    async def route(self, *args, **kwargs):  # noqa: ANN002, ANN003
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
    wiring._translation = svc  # noqa: SLF001 — test seam for mid-session service
    wiring.apply_translation_lang({SETTING_LIVE_TRANSLATION_LANG: "French"})
    assert svc._target_lang == "French"  # noqa: SLF001


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
    wiring._session_router = router  # noqa: SLF001
    wiring._session_emit_translation = emit  # noqa: SLF001
    wiring._session_preferred_model = None  # noqa: SLF001
    wiring._session_preferred_provider = None  # noqa: SLF001
    wiring._combined = combined  # noqa: SLF001
    wiring._translation = None  # noqa: SLF001

    wiring.apply_translation_lang({SETTING_LIVE_TRANSLATION_LANG: "German"})

    assert wiring._translation is not None  # noqa: SLF001
    assert wiring._translation._target_lang == "German"  # noqa: SLF001
    assert combined._translation is wiring._translation  # noqa: SLF001
