"""meeting.delete — remove from Library, wipe kept audio, leave vault note."""

from pathlib import Path

import pytest

from engine.enhance.meeting_finalization_service import MeetingFinalizationService
from engine.protocol import EventBroadcastHub
from engine.storage.sqlite_connection import open_sqlite_connection
from engine.stt.keep_audio_recorder import keep_audio_directory
from tests.enhance_test_support import seed_meeting


@pytest.mark.asyncio
async def test_delete_meeting_removes_from_list_and_wipes_kept_audio(
    tmp_path: Path,
    real_migrations_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = tmp_path / "test.db"
    audio_root = tmp_path / "audio"
    monkeypatch.setenv("OMNI_AUDIO_DIR", str(audio_root))

    meeting_id = "m-del-1"
    session_dir = keep_audio_directory() / meeting_id
    session_dir.mkdir(parents=True)
    (session_dir / "them.mp3").write_bytes(b"fake-mp3")
    (session_dir / "me.mp3").write_bytes(b"fake-mp3")

    vault_note = tmp_path / "vault" / "Meetings" / "note.md"
    vault_note.parent.mkdir(parents=True)
    vault_note.write_text("user note — must survive delete", encoding="utf-8")

    await seed_meeting(db, real_migrations_dir, meeting_id)
    connection = await open_sqlite_connection(db)
    try:
        await connection.execute(
            "UPDATE meetings SET note_path = ? WHERE id = ?",
            ("Meetings/note.md", meeting_id),
        )
        await connection.commit()
    finally:
        await connection.close()

    hub = EventBroadcastHub()
    service = MeetingFinalizationService(
        db_path=db, migrations_dir=real_migrations_dir, hub=hub
    )

    result = await service.delete_meeting(meeting_id)
    assert result == {"deleted": True, "vault_note_kept": True}

    rows = await service.list_meetings()
    assert rows == []
    assert await service.get_meeting(meeting_id) is None
    assert not session_dir.exists()
    assert vault_note.read_text(encoding="utf-8") == "user note — must survive delete"

    connection = await open_sqlite_connection(db)
    try:
        cursor = await connection.execute(
            "SELECT COUNT(*) FROM transcript_segments WHERE meeting_id = ?",
            (meeting_id,),
        )
        _row = await cursor.fetchone()
        assert _row is not None
        assert _row[0] == 0
        await cursor.close()
        cursor = await connection.execute(
            "SELECT deleted_at FROM meetings WHERE id = ?", (meeting_id,)
        )
        _row = await cursor.fetchone()
        assert _row is not None
        deleted_at = _row[0]
        await cursor.close()
        assert deleted_at is not None
    finally:
        await connection.close()


@pytest.mark.asyncio
async def test_delete_meeting_unknown_id_returns_none(
    tmp_path: Path, real_migrations_dir: Path
) -> None:
    db = tmp_path / "test.db"
    service = MeetingFinalizationService(
        db_path=db,
        migrations_dir=real_migrations_dir,
        hub=EventBroadcastHub(),
    )
    assert await service.delete_meeting("missing") is None


@pytest.mark.asyncio
async def test_delete_meeting_idempotent_second_call_returns_none(
    tmp_path: Path, real_migrations_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db = tmp_path / "test.db"
    monkeypatch.setenv("OMNI_AUDIO_DIR", str(tmp_path / "audio"))
    await seed_meeting(db, real_migrations_dir, "m-1")
    service = MeetingFinalizationService(
        db_path=db,
        migrations_dir=real_migrations_dir,
        hub=EventBroadcastHub(),
    )
    assert await service.delete_meeting("m-1") == {
        "deleted": True,
        "vault_note_kept": True,
    }
    assert await service.delete_meeting("m-1") is None


@pytest.mark.asyncio
async def test_delete_meeting_purges_transcript_index_including_notes_meta(
    tmp_path: Path, real_migrations_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Soft-delete must remove transcript:// rows via indexer._remove_note
    (chunks + notes_meta + links), not a bare DELETE FROM chunks."""
    from engine.index.vault_indexer_service import VaultIndexerService

    db = tmp_path / "test.db"
    monkeypatch.setenv("OMNI_AUDIO_DIR", str(tmp_path / "audio"))
    await seed_meeting(db, real_migrations_dir, "m-idx")
    connection = await open_sqlite_connection(db)
    try:
        indexer = VaultIndexerService(connection, tmp_path / "vault")
        assert await indexer.index_meeting_transcript("m-idx") >= 1
        cursor = await connection.execute(
            "SELECT COUNT(*) FROM notes_meta WHERE note_path = 'transcript://m-idx'"
        )
        _row = await cursor.fetchone()
        assert _row is not None
        assert _row[0] == 1
        await cursor.close()
        cursor = await connection.execute(
            "SELECT COUNT(*) FROM chunks WHERE note_path = 'transcript://m-idx'"
        )
        _row = await cursor.fetchone()
        assert _row is not None
        assert _row[0] >= 1
        await cursor.close()
    finally:
        await connection.close()

    service = MeetingFinalizationService(
        db_path=db,
        migrations_dir=real_migrations_dir,
        hub=EventBroadcastHub(),
    )
    assert await service.delete_meeting("m-idx") == {
        "deleted": True,
        "vault_note_kept": True,
    }

    connection = await open_sqlite_connection(db)
    try:
        cursor = await connection.execute(
            "SELECT COUNT(*) FROM notes_meta WHERE note_path = 'transcript://m-idx'"
        )
        _row = await cursor.fetchone()
        assert _row is not None
        assert _row[0] == 0
        await cursor.close()
        cursor = await connection.execute(
            "SELECT COUNT(*) FROM chunks WHERE note_path = 'transcript://m-idx'"
        )
        _row = await cursor.fetchone()
        assert _row is not None
        assert _row[0] == 0
        await cursor.close()
        cursor = await connection.execute(
            "SELECT COUNT(*) FROM links WHERE src_note = 'transcript://m-idx'"
        )
        _row = await cursor.fetchone()
        assert _row is not None
        assert _row[0] == 0
        await cursor.close()
    finally:
        await connection.close()
