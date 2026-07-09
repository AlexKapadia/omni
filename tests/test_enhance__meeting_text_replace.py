"""Tests for meeting text replace."""

import pytest

from engine.enhance.meeting_finalization_service import MeetingFinalizationService
from engine.protocol import EventBroadcastHub
from engine.storage.meetings_repository import record_meeting_finalization, utc_now_iso
from engine.storage.sqlite_connection import open_sqlite_connection
from tests.enhance_test_support import seed_meeting


@pytest.mark.asyncio
async def test_replace_meeting_text_updates_transcript_and_notes(
    tmp_path,
    real_migrations_dir,
) -> None:
    db = tmp_path / "test.db"
    hub = EventBroadcastHub()
    service = MeetingFinalizationService(db_path=db, migrations_dir=real_migrations_dir, hub=hub)
    await seed_meeting(
        db,
        real_migrations_dir,
        "m-1",
        segments=(("them", "We need the security review"), ("me", "I will own it")),
    )
    connection = await open_sqlite_connection(db)
    try:
        await record_meeting_finalization(
            connection,
            "m-1",
            note_path="Meetings/standup.md",
            notes_text="notes",
            enhanced_notes_md="Them: security review deadline Friday.",
            finalized_at_iso=utc_now_iso(),
        )
        await connection.commit()
    finally:
        await connection.close()

    result = await service.replace_meeting_text(
        "m-1", "security review", "sec review", "both"
    )
    assert result == {"transcript_segments": 1, "enhanced_notes": 1}

    loaded = await service.get_meeting("m-1")
    assert loaded is not None
    row, segments, _extraction = loaded
    assert "sec review" in segments[0].text
    assert row.enhanced_notes_md is not None
    assert "sec review" in row.enhanced_notes_md
