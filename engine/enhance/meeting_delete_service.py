"""Soft-delete a meeting from the Library and wipe kept audio.

Purpose: privacy purge for recordings — remove the meeting from Library,
delete transcript segments and the keep-audio session directory, leave the
vault note (user may still want it). Hard-delete of the meetings row is
impossible while extraction_results / approval_cards are append-only with
FKs, so we stamp ``deleted_at`` and filter it from list/get.
Pipeline position: called by ``MeetingFinalizationService.delete_meeting``
for the ``meeting.delete`` WS command.
"""

from __future__ import annotations

import logging
import shutil
from pathlib import Path

from engine.index.vault_indexer_service import (
    TRANSCRIPT_NOTE_PATH_PREFIX,
    VaultIndexerService,
)
from engine.storage.meetings_repository import soft_delete_meeting_row, utc_now_iso
from engine.storage.sqlite_connection import open_sqlite_connection
from engine.storage.sqlite_migrations_runner import apply_migrations
from engine.storage.transcript_segments_repository import (
    delete_transcript_segments_for_meeting,
)
from engine.stt.keep_audio_recorder import keep_audio_directory

logger = logging.getLogger(__name__)


async def delete_meeting(
    db_path: Path,
    migrations_dir: Path,
    meeting_id: str,
) -> dict[str, object] | None:
    """Soft-delete meeting + wipe segments/audio. None when unknown/already gone.

    Reply shape for the WS layer: ``{deleted: true, vault_note_kept: true}``.
    The vault note is never deleted here (privacy mandate is about recordings).
    """
    await apply_migrations(db_path, migrations_dir)
    connection = await open_sqlite_connection(db_path)
    try:
        stamped = await soft_delete_meeting_row(connection, meeting_id, utc_now_iso())
        if not stamped:
            return None
        await delete_transcript_segments_for_meeting(connection, meeting_id)
        await connection.commit()
        # Full indexer remove: chunks + notes_meta + links + best-effort vec.
        # Failures must not undo the Library delete (vault note stays indexed).
        try:
            note_path = f"{TRANSCRIPT_NOTE_PATH_PREFIX}{meeting_id}"
            indexer = VaultIndexerService(connection, Path("."))
            await indexer._remove_note(note_path)
        except Exception:
            logger.warning(
                "index cleanup failed for deleted meeting %s",
                meeting_id,
                exc_info=True,
            )
    finally:
        await connection.close()

    session_dir = keep_audio_directory() / meeting_id
    if session_dir.is_dir():
        try:
            shutil.rmtree(session_dir)
        except OSError:
            logger.warning(
                "kept-audio wipe failed for meeting %s at %s",
                meeting_id,
                session_dir,
                exc_info=True,
            )

    return {"deleted": True, "vault_note_kept": True}
