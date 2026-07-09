"""Tests for meeting-scoped ask."""

import pytest

from engine.ask.ask_omni_answer_service import AskOmniAnswerService
from engine.index.hybrid_rrf_retriever import HybridRrfRetriever
from engine.storage.meetings_repository import record_meeting_finalization, utc_now_iso
from engine.storage.sqlite_connection import open_sqlite_connection
from tests.enhance_test_support import seed_meeting


class _FakeRouter:
    last_user: str = ""

    async def route(self, task, system_frame, messages, **kwargs):
        self.last_user = messages[0].content

        class _Completion:
            text = '{"headline":"Answer","answer":"Friday."}'

        class _Routed:
            completion = _Completion()

        return _Routed()


@pytest.mark.asyncio
async def test_meeting_scoped_ask_uses_meeting_context(tmp_path, real_migrations_dir) -> None:
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
