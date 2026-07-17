"""Tests for meeting-scoped ask."""

from pathlib import Path

import pytest

from engine.ask.ask_omni_answer_service import AskOmniAnswerService
from engine.index.hybrid_rrf_retriever import HybridRrfRetriever
from engine.router.completion_contract import (
    ChatMessage,
    Provider,
    ProviderCompletion,
    RoutedCompletion,
    ToolSpec,
)
from engine.storage.meetings_repository import record_meeting_finalization, utc_now_iso
from engine.storage.sqlite_connection import open_sqlite_connection
from tests.enhance_test_support import seed_meeting


class _FakeRouter:
    last_user: str = ""

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
        self.last_user = messages[0].content
        return RoutedCompletion(
            completion=ProviderCompletion(
                text='{"headline":"Answer","answer":"Friday."}',
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
async def test_meeting_scoped_ask_uses_meeting_context(
    tmp_path: Path, real_migrations_dir: Path
) -> None:
    db = tmp_path / "test.db"
    await seed_meeting(
        db,
        real_migrations_dir,
        "m-ask",
        title="Budget call",
        segments=(("them", "Deadline is Friday"),),
    )
    connection = await open_sqlite_connection(db)
    try:
        await record_meeting_finalization(
            connection,
            "m-ask",
            note_path="Meetings/budget.md",
            notes_text="",
            enhanced_notes_md="## Summary\nBudget approved.",
            finalized_at_iso=utc_now_iso(),
        )
        await connection.commit()
    finally:
        await connection.close()

    connection = await open_sqlite_connection(db)
    router = _FakeRouter()
    service = AskOmniAnswerService(connection, HybridRrfRetriever(connection, None, None), router)
    answer = await service.answer("When is the deadline?", meeting_id="m-ask")
    await connection.close()

    assert "Friday" in answer.answer_md
    assert "Budget call" in router.last_user
    assert "Deadline is Friday" in router.last_user
