"""Isolated finalization steps: enhance, actions region, daily line, wiring.

Purpose: the individually-failable pieces of the finalization pipeline,
kept out of the orchestrating service so each step's isolation contract
(fail -> honest warning, never a crash, never lost user content) is small
and independently testable.
Pipeline position: called only by
``engine.enhance.meeting_finalization_service``.

Resilience invariant: NOTHING here raises past its function once the vault
note exists — every failure becomes a plain warning string and, where the
note has a matching region, an honest in-note marker.
"""

import logging
import re
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

import aiosqlite

from engine.enhance.enhanced_notes_pipeline import EnhancementOutputError, run_enhanced_notes
from engine.enhance.meeting_extraction_pipeline import (
    ExtractionOutcome,
    format_actions_checklist,
)
from engine.enhance.note_templates import NoteTemplate
from engine.router import ProviderRouter, RouterError, build_provider_clients
from engine.router.fallback_executor import LedgerRecorder
from engine.router.router_ledger_repository import RouterLedgerEntry, insert_router_ledger_entry
from engine.security.provider_key_store import ProviderKeyStore
from engine.storage.meetings_repository import MeetingRow
from engine.vault import (
    VaultWriteError,
    append_daily_note_line,
    update_meeting_actions,
    update_meeting_enhanced_notes,
)

logger = logging.getLogger(__name__)

# Injectable factory seam: tests hand in a fake router; production builds
# keyed clients at CALL time (fail closed per call, inert construction).
RouterFactory = Callable[[LedgerRecorder], ProviderRouter]
VaultRootResolver = Callable[[], Path]


def default_router_factory(recorder: LedgerRecorder) -> ProviderRouter:
    """Real router: keyed clients only, ledger-bound (built per finalize)."""
    clients = build_provider_clients(ProviderKeyStore())
    return ProviderRouter(clients, recorder)


def ledger_recorder_for(connection: aiosqlite.Connection) -> LedgerRecorder:
    """Bind the append-only router ledger writer to this run's connection."""

    async def record(entry: RouterLedgerEntry) -> None:
        await insert_router_ledger_entry(connection, entry)

    return record


# Frontmatter refuses control characters (fail closed) — titles are user
# input, so they get a presentation-only cleanup before note creation.
_TITLE_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]+")


def frontmatter_safe_title(title: str) -> str:
    """Collapse control characters in a meeting title for the vault note.

    Presentation only — the meetings row keeps the original bytes. Without
    this, a newline-bearing title would make its meeting permanently
    unfinalizable (the frontmatter codec fails closed on control chars).
    """
    cleaned = _TITLE_CONTROL_CHARS.sub(" ", title).strip()
    return cleaned or "Untitled meeting"


def plain_reason(error: object) -> str:
    """A short, plain-voice, sentinel-free reason safe for the vault note.

    The vault writer refuses managed-marker sentinels anywhere in content
    (region-injection defence), so error text is scrubbed before it may be
    written as an honest in-note marker.
    """
    text = str(error) if error is not None else "unknown reason"
    return text.replace("omni:managed", "omni-managed")[:300]


async def run_enhance_step(
    router: ProviderRouter,
    template: NoteTemplate,
    notepad_text: str,
    transcript_lines: list[str],
    note_path: Path,
    warnings: list[str],
) -> tuple[bool, str | None]:
    """Enhancement + managed-region write, isolated.

    Returns ``(ok, sanitised_markdown_or_None)``. On failure the enhanced
    region gets an honest "unavailable" marker; if even that write fails
    (e.g. user text corrupted the markers) it becomes a second warning —
    the raw note is never lost either way.
    """
    try:
        result = await run_enhanced_notes(router, template, notepad_text, transcript_lines)
        update_meeting_enhanced_notes(note_path, result.markdown)
        return True, result.markdown
    except (RouterError, EnhancementOutputError, VaultWriteError) as exc:
        reason = plain_reason(exc)
        warnings.append(f"enhancement unavailable: {reason}")
        try:
            update_meeting_enhanced_notes(note_path, f"_Enhancement unavailable: {reason}_")
        except VaultWriteError as marker_exc:
            warnings.append(f"could not mark enhanced region: {plain_reason(marker_exc)}")
        return False, None


def write_actions_region_step(
    note_path: Path, outcome: ExtractionOutcome, warnings: list[str]
) -> None:
    """Actions managed-region write, isolated (honest marker on absence).

    The checklist is a human-readable rendering only — approval cards (M4)
    read the persisted extraction payload, never this markdown
    (approval-before-execute invariant).
    """
    if outcome.extraction is not None:
        content = format_actions_checklist(outcome.extraction)
    else:
        content = f"_Extraction unavailable: {plain_reason(outcome.failure_reason)}_"
    try:
        update_meeting_actions(note_path, content)
    except VaultWriteError as exc:
        warnings.append(f"could not update actions region: {plain_reason(exc)}")


def append_daily_line_step(
    vault_root: Path,
    row: MeetingRow,
    note_rel: str,
    outcome: ExtractionOutcome,
    warnings: list[str],
) -> None:
    """Daily-note log line, isolated (single-line contract enforced here)."""
    action_count = len(outcome.extraction.actions) if outcome.extraction is not None else 0
    line = (
        f"- Meeting captured: {row.title} -> {note_rel}"
        f" ({action_count} action(s) pending approval)"
    )
    try:
        append_daily_note_line(
            vault_root,
            date_iso=datetime.now(tz=UTC).date().isoformat(),
            # Titles are user input: collapse any newline so one meeting can
            # never forge extra daily-log entries (log-forging defence).
            line=line.replace("\r", " ").replace("\n", " "),
        )
    except VaultWriteError as exc:
        warnings.append(f"could not append daily-note line: {plain_reason(exc)}")
