"""Meeting finalization: capture output + notepad -> vault note, enhanced & indexed.

Purpose: orchestrates everything that happens when the user finalizes a
meeting — reads the persisted segments, creates the vault note (user notes
byte-identical, transcript verbatim), runs template selection, extraction,
and enhancement through the router, updates the managed regions, records
finalization state, indexes the meeting, and appends the daily-log line.
Also serves the Library's ``meetings.list`` / ``meeting.get`` reads.
Pipeline position: invoked by ``meeting_command_dispatcher``; sits above
``engine.vault`` / ``engine.router`` / ``engine.index`` / ``engine.storage``.

Fidelity / resilience invariants:
- The user's notes reach the DB EXACTLY as typed and the vault note with
  interior bytes untouched (fidelity mandate; the note writer's only touch
  is structural trailing whitespace at creation).
- STEP ISOLATION: extraction, enhancement, region updates, indexing, and
  the daily line each fail independently — a failing step leaves prior
  steps intact and marks the note honestly; the raw note is never lost.
- Refusals are FAIL CLOSED and happen before any write: unknown meeting,
  meeting still capturing, duplicate finalize, unknown template, or an
  unconfigured vault all refuse with a plain reason.
"""

import base64
import logging
from pathlib import Path

import aiosqlite

from engine.enhance.meeting_extraction_pipeline import run_meeting_extraction
from engine.enhance.meeting_finalization_result_types import (
    FinalizationResult,
    FinalizeRefusedError,
)
from engine.enhance.meeting_finalization_steps import (
    RouterFactory,
    VaultRootResolver,
    append_daily_line_step,
    default_router_factory,
    frontmatter_safe_title,
    ledger_recorder_for,
    run_enhance_step,
    write_actions_region_step,
)
from engine.enhance.note_templates import (
    NoteTemplate,
    resolve_template,
    select_template_for_transcript,
)
from engine.index import VaultIndexerService
from engine.protocol import (
    EVENT_ENHANCE_FAILED,
    EVENT_ENHANCE_READY,
    EVENT_ENHANCE_STARTED,
    EventBroadcastHub,
    build_enhance_failed_payload,
    build_enhance_ready_payload,
    build_enhance_started_payload,
)
from engine.storage.extraction_results_repository import (
    insert_extraction_result,
    latest_extraction_payload_json,
)
from engine.storage.meetings_repository import (
    MeetingRow,
    fetch_meeting_row,
    list_meeting_rows,
    record_meeting_finalization,
    utc_now_iso,
)
from engine.storage.sqlite_connection import open_sqlite_connection
from engine.storage.sqlite_migrations_runner import apply_migrations
from engine.storage.transcript_segments_repository import (
    TranscriptSegmentRow,
    list_transcript_segment_rows,
    update_transcript_segment_text,
)
from engine.export.document_export import export_transcript_docx, export_transcript_pdf
from engine.export.transcript_export import (
    export_transcript_srt,
    export_transcript_txt,
    export_transcript_vtt,
)
from engine.vault import VaultWriteError, create_meeting_note, resolve_vault_root

logger = logging.getLogger(__name__)


class MeetingFinalizationService:
    """One per engine process; construction is inert (no keys, no I/O).

    ``router_factory`` receives the per-run ledger recorder and returns the
    router; the default builds real provider clients from the key store at
    CALL time (fail closed per call — never at construction).
    """

    def __init__(
        self,
        db_path: Path,
        migrations_dir: Path,
        hub: EventBroadcastHub,
        router_factory: RouterFactory | None = None,
        vault_root_resolver: VaultRootResolver | None = None,
    ) -> None:
        self.db_path = db_path
        self.migrations_dir = migrations_dir
        self._hub = hub
        self._router_factory = router_factory if router_factory else default_router_factory
        self._vault_root_resolver = (
            vault_root_resolver if vault_root_resolver else resolve_vault_root
        )

    # ------------------------------------------------------------------ reads
    async def list_meetings(self) -> list[MeetingRow]:
        """All meeting rows for ``meetings.list`` (schema ensured first)."""
        await apply_migrations(self.db_path, self.migrations_dir)
        connection = await open_sqlite_connection(self.db_path)
        try:
            return await list_meeting_rows(connection)
        finally:
            await connection.close()

    async def get_meeting(
        self, meeting_id: str
    ) -> tuple[MeetingRow, list[TranscriptSegmentRow], str | None] | None:
        """One meeting + segments + latest extraction JSON for ``meeting.get``."""
        await apply_migrations(self.db_path, self.migrations_dir)
        connection = await open_sqlite_connection(self.db_path)
        try:
            row = await fetch_meeting_row(connection, meeting_id)
            if row is None:
                return None
            segments = await list_transcript_segment_rows(connection, meeting_id)
            extraction = await latest_extraction_payload_json(connection, meeting_id)
            return row, segments, extraction
        finally:
            await connection.close()

    async def update_transcript_segment(
        self, meeting_id: str, segment_id: str, text: str
    ) -> bool:
        """Edit one segment's text; refuses when meeting is still capturing."""
        await apply_migrations(self.db_path, self.migrations_dir)
        connection = await open_sqlite_connection(self.db_path)
        try:
            row = await fetch_meeting_row(connection, meeting_id)
            if row is None or row.ended_at is None:
                return False
            changed = await update_transcript_segment_text(
                connection, meeting_id, segment_id, text
            )
            if changed:
                await connection.commit()
            return changed
        finally:
            await connection.close()

    async def export_transcript(self, meeting_id: str, fmt: str) -> dict[str, object] | None:
        """Export transcript; None when meeting unknown."""
        await apply_migrations(self.db_path, self.migrations_dir)
        connection = await open_sqlite_connection(self.db_path)
        try:
            row = await fetch_meeting_row(connection, meeting_id)
            if row is None:
                return None
            segments = await list_transcript_segment_rows(connection, meeting_id)
        finally:
            await connection.close()
        if fmt == "srt":
            return {"content": export_transcript_srt(segments), "format": fmt}
        if fmt == "vtt":
            return {"content": export_transcript_vtt(segments), "format": fmt}
        if fmt == "txt":
            return {"content": export_transcript_txt(segments), "format": fmt}
        if fmt == "pdf":
            data = export_transcript_pdf(segments)
            return {
                "content": base64.b64encode(data).decode("ascii"),
                "encoding": "base64",
                "format": fmt,
            }
        if fmt == "docx":
            data = export_transcript_docx(segments)
            return {
                "content": base64.b64encode(data).decode("ascii"),
                "encoding": "base64",
                "format": fmt,
            }
        return None

    async def retranscribe(self, meeting_id: str) -> None:
        from engine.enhance.meeting_retranscription_service import retranscribe_meeting

        await retranscribe_meeting(self.db_path, self.migrations_dir, meeting_id)

    # --------------------------------------------------------------- finalize
    async def finalize(
        self, meeting_id: str, notepad_text: str, template_id: str | None
    ) -> FinalizationResult:
        """Run the full finalization pipeline for one ended meeting.

        Raises ``FinalizeRefusedError`` on the fail-closed refusals listed in
        the module docstring. After the note exists, nothing raises: every
        later step degrades into an honest warning on the result.
        """
        await apply_migrations(self.db_path, self.migrations_dir)
        connection = await open_sqlite_connection(self.db_path)
        try:
            row, explicit_template, vault_root = await self._validate_request(
                connection, meeting_id, template_id
            )
            await self._hub.broadcast_event(
                EVENT_ENHANCE_STARTED, build_enhance_started_payload(meeting_id)
            )
            segments = await list_transcript_segment_rows(connection, meeting_id)
            transcript_lines = [
                f"{'Me' if s.stream == 'me' else 'Them'}: {s.text}" for s in segments
            ]
            router = self._router_factory(ledger_recorder_for(connection))
            warnings: list[str] = []

            # STEP template (isolated): explicit id wins; the auto selector
            # falls back to General internally — it cannot fail the run.
            template: NoteTemplate = explicit_template or await select_template_for_transcript(
                router, notepad_text, transcript_lines
            )

            # STEP extraction (isolated; BEFORE note creation so contacts can
            # seed frontmatter attendees — frontmatter is user territory
            # after creation and can never be edited later).
            outcome = await run_meeting_extraction(router, notepad_text, transcript_lines)
            if outcome.extraction is not None:
                await insert_extraction_result(
                    connection, meeting_id, utc_now_iso(), outcome.extraction.model_dump_json()
                )
            else:
                warnings.append(f"extraction unavailable: {outcome.failure_reason}")

            # STEP create note — the last step allowed to refuse the run
            # (without the note there is nothing to finalize into).
            attendees = (
                [contact.name for contact in outcome.extraction.contacts][:8]
                if outcome.extraction is not None
                else []
            )
            try:
                note_path = create_meeting_note(
                    vault_root,
                    # Presentation-only cleanup: a control-char-bearing title
                    # must never make the meeting unfinalizable (the DB row
                    # keeps the original bytes; frontmatter rejects newlines).
                    title=frontmatter_safe_title(row.title),
                    date_iso=row.started_at[:10],
                    attendees=attendees,
                    tags=("meeting", template.template_id),
                    my_notes=notepad_text,  # byte-identical (fidelity mandate)
                    transcript_lines=transcript_lines,
                )
            except VaultWriteError as exc:
                await self._hub.broadcast_event(
                    EVENT_ENHANCE_FAILED, build_enhance_failed_payload(meeting_id, str(exc))
                )
                raise FinalizeRefusedError(f"could not create the vault note: {exc}") from exc
            note_rel = note_path.relative_to(vault_root).as_posix()

            # STEP enhance + STEP actions region (both isolated).
            enhance_ok, enhanced_md = await run_enhance_step(
                router, template, notepad_text, transcript_lines, note_path, warnings
            )
            write_actions_region_step(note_path, outcome, warnings)

            # STEP record finalization state (source for meetings.list/get).
            await record_meeting_finalization(
                connection,
                meeting_id,
                note_path=note_rel,
                notes_text=notepad_text,  # exact bytes as typed
                enhanced_notes_md=enhanced_md,
                finalized_at_iso=utc_now_iso(),
            )

            # STEP index (isolated): search must never cost the user the note.
            indexed_chunks = 0
            try:
                indexer = VaultIndexerService(connection, vault_root)
                indexed_chunks = await indexer.index_meeting_transcript(meeting_id)
                report = await indexer.index_changed_files([note_path])
                indexed_chunks += report.chunks_written
            except Exception as exc:  # index failure is non-fatal by design
                warnings.append(f"indexing unavailable: {exc}")

            # STEP daily-log line (isolated).
            append_daily_line_step(vault_root, row, note_rel, outcome, warnings)

            await self._broadcast_outcome(meeting_id, note_rel, enhance_ok, warnings)
            logger.info(
                "meeting %s finalized -> %s (enhance_ok=%s extraction_ok=%s warnings=%d)",
                meeting_id,
                note_rel,
                enhance_ok,
                outcome.extraction is not None,
                len(warnings),
            )
            return FinalizationResult(
                meeting_id=meeting_id,
                note_path=note_rel,
                template_id=template.template_id,
                enhance_ok=enhance_ok,
                extraction_ok=outcome.extraction is not None,
                indexed_chunks=indexed_chunks,
                warnings=tuple(warnings),
            )
        finally:
            await connection.close()

    async def _validate_request(
        self, connection: aiosqlite.Connection, meeting_id: str, template_id: str | None
    ) -> tuple[MeetingRow, NoteTemplate | None, Path]:
        """All fail-closed refusals, before any write or event."""
        row = await fetch_meeting_row(connection, meeting_id)
        if row is None:
            raise FinalizeRefusedError(f"meeting {meeting_id!r} does not exist")
        if row.ended_at is None:
            raise FinalizeRefusedError("meeting is still capturing; stop it first")
        if row.finalized_at is not None:
            # fail-closed: a second run would fork the note silently.
            raise FinalizeRefusedError("meeting is already finalized")
        try:
            explicit_template = resolve_template(template_id)
        except ValueError as exc:
            raise FinalizeRefusedError(str(exc)) from exc
        try:
            vault_root = self._vault_root_resolver()
        except VaultWriteError as exc:  # includes VaultNotConfiguredError
            raise FinalizeRefusedError(str(exc)) from exc
        return row, explicit_template, vault_root

    async def _broadcast_outcome(
        self, meeting_id: str, note_rel: str, enhance_ok: bool, warnings: list[str]
    ) -> None:
        """enhance.ready on success; enhance.failed with the honest story."""
        if enhance_ok:
            await self._hub.broadcast_event(
                EVENT_ENHANCE_READY, build_enhance_ready_payload(meeting_id, note_rel)
            )
        else:
            reason = "; ".join(warnings) if warnings else "enhancement failed"
            await self._hub.broadcast_event(
                EVENT_ENHANCE_FAILED, build_enhance_failed_payload(meeting_id, reason)
            )
