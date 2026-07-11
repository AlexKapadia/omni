"""Segment edit must sync vault transcript region and reindex fail-soft."""

from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from engine.enhance.meeting_finalization_service import MeetingFinalizationService
from engine.index.vault_indexer_service import VaultIndexerService
from engine.protocol import EventBroadcastHub
from engine.storage.meetings_repository import record_meeting_finalization, utc_now_iso
from engine.storage.sqlite_connection import open_sqlite_connection
from engine.vault.meeting_note_writer import create_meeting_note
from tests.enhance_test_support import seed_meeting


@pytest.mark.asyncio
async def test_update_transcript_segment_syncs_vault_and_reindexes(
    tmp_path: Path,
    real_migrations_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    note = create_meeting_note(
        vault,
        title="standup",
        date_iso="2026-07-06",
        my_notes="scratch",
        transcript_lines=["Them: original wording"],
    )
    note_rel = note.relative_to(vault).as_posix()

    db = tmp_path / "test.db"
    hub = EventBroadcastHub()
    service = MeetingFinalizationService(
        db_path=db,
        migrations_dir=real_migrations_dir,
        hub=hub,
        vault_root_resolver=lambda: vault,
    )
    await seed_meeting(
        db,
        real_migrations_dir,
        "m-seg",
        segments=(("them", "original wording"),),
    )
    connection = await open_sqlite_connection(db)
    try:
        await record_meeting_finalization(
            connection,
            "m-seg",
            note_path=note_rel,
            notes_text="scratch",
            enhanced_notes_md=None,
            finalized_at_iso=utc_now_iso(),
        )
        await connection.commit()
    finally:
        await connection.close()

    reindex = AsyncMock(return_value=1)
    monkeypatch.setattr(VaultIndexerService, "index_meeting_transcript", reindex)

    changed = await service.update_transcript_segment(
        "m-seg", "m-seg-seg-0", "edited wording"
    )
    assert changed is True

    text = note.read_text(encoding="utf-8")
    assert "edited wording" in text
    assert "original wording" not in text
    reindex.assert_awaited()
