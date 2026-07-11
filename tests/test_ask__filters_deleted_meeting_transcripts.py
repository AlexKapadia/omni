"""Ask all-scope must not cite soft-deleted meeting transcript:// chunks."""

from pathlib import Path

import pytest

from engine.ask.ask_deleted_meeting_filter import filter_deleted_meeting_chunks
from engine.index.retrieved_chunk_types import RetrievedChunk
from engine.storage import apply_migrations, open_sqlite_connection


def _chunk(chunk_id: int, note_path: str) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=chunk_id,
        note_path=note_path,
        source_type="transcript" if note_path.startswith("transcript://") else "vault",
        note_title="T",
        heading_path="",
        line_start=1,
        line_end=1,
        text="secret deleted content",
        contextualized_text="secret deleted content",
        score=1.0,
        retrieval_source="hybrid_rrf",
    )


@pytest.mark.asyncio
async def test_filter_drops_transcript_chunks_for_soft_deleted_meetings(
    tmp_path: Path, real_migrations_dir: Path
) -> None:
    db = tmp_path / "ask.db"
    await apply_migrations(db, real_migrations_dir)
    connection = await open_sqlite_connection(db)
    try:
        await connection.execute(
            "INSERT INTO meetings (id, title, started_at, deleted_at)"
            " VALUES ('gone', 'Gone', '2026-07-01T00:00:00+00:00',"
            " '2026-07-10T00:00:00+00:00')"
        )
        await connection.execute(
            "INSERT INTO meetings (id, title, started_at)"
            " VALUES ('live', 'Live', '2026-07-01T00:00:00+00:00')"
        )
        await connection.commit()
        chunks = [
            _chunk(1, "transcript://gone"),
            _chunk(2, "transcript://live"),
            _chunk(3, "Meetings/kept.md"),
        ]
        kept = await filter_deleted_meeting_chunks(connection, chunks)
        assert [c.note_path for c in kept] == [
            "transcript://live",
            "Meetings/kept.md",
        ]
    finally:
        await connection.close()
