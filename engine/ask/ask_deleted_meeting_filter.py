"""Filter Ask retrieval so soft-deleted meeting transcripts are never cited.

Purpose: defence-in-depth after soft-delete index purge — if orphan
``transcript://{id}`` chunks remain (partial cleanup, race, reindex), Ask
all-scope must still drop them when ``meetings.deleted_at`` is set.
Pipeline position: applied to structured-first / hybrid chunks inside
``AskOmniAnswerService.answer`` before synthesis.
"""

from __future__ import annotations

from collections.abc import Sequence

import aiosqlite

from engine.index.retrieved_chunk_types import RetrievedChunk
from engine.index.vault_indexer_service import TRANSCRIPT_NOTE_PATH_PREFIX


async def filter_deleted_meeting_chunks(
    connection: aiosqlite.Connection,
    chunks: Sequence[RetrievedChunk],
) -> list[RetrievedChunk]:
    """Drop chunks whose note_path is ``transcript://{id}`` for a soft-deleted meeting."""
    transcript_ids: list[str] = []
    for chunk in chunks:
        if chunk.note_path.startswith(TRANSCRIPT_NOTE_PATH_PREFIX):
            transcript_ids.append(chunk.note_path[len(TRANSCRIPT_NOTE_PATH_PREFIX) :])
    if not transcript_ids:
        return list(chunks)
    placeholders = ",".join("?" * len(transcript_ids))
    cursor = await connection.execute(
        f"SELECT id FROM meetings WHERE id IN ({placeholders}) AND deleted_at IS NOT NULL",  # noqa: S608
        transcript_ids,
    )
    deleted = {str(row[0]) for row in await cursor.fetchall()}
    await cursor.close()
    if not deleted:
        return list(chunks)
    return [
        chunk
        for chunk in chunks
        if not (
            chunk.note_path.startswith(TRANSCRIPT_NOTE_PATH_PREFIX)
            and chunk.note_path[len(TRANSCRIPT_NOTE_PATH_PREFIX) :] in deleted
        )
    ]
