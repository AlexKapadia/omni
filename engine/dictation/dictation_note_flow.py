"""NOTE-mode persistence: title -> Inbox note (cleaned body, raw kept) -> index.

Purpose: the note-mode half of release finalization, extracted from
``dictation_finalization`` so each mode's flow stays a single-responsibility
unit. Resolves a short title via the router, writes ``Inbox/{title}.md``
with the CLEANED text as the body and the RAW verbatim transcript retained
in a collapsed section (fidelity mandate: raw is ground truth and is stored
byte-identical), indexes the new note incrementally, and appends a
daily-note log line.
Pipeline position: called only by ``DictationReleaseFinalizer._finalize_note``.

Fidelity / degradation invariants:
- The raw transcript reaches the vault byte-identical, always.
- Title/index/daily failures degrade honestly (reported, note kept);
  vault-write failure propagates (an unsaved note must not look saved).
"""

import logging
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Protocol

from engine.dictation.dictation_note_titler import (
    RouteCompletionFn,
    resolve_dictation_note_title,
)
from engine.vault.daily_note_appender import append_daily_note_line
from engine.vault.inbox_dictation_writer import create_inbox_dictation_note

logger = logging.getLogger(__name__)


class NoteIndexerProtocol(Protocol):
    """The slice of ``engine.index.VaultIndexerService`` dictation needs.

    A Protocol (not the concrete class) keeps this module decoupled from
    the index layer's construction and lets tests inject fakes.
    """

    async def index_changed_files(self, changed_paths: Iterable[Path]) -> object: ...


@dataclass(frozen=True)
class NoteFlowOutcome:
    """Everything the finalizer needs to report a saved note honestly."""

    note_path: str
    note_title: str
    title_source: str
    provider: str | None
    model: str | None
    latency_ms: int | None
    degraded_reason: str | None


async def persist_dictation_note(
    *,
    route: RouteCompletionFn,
    vault_root: Path,
    verbatim_text: str,
    body_markdown: str,
    now: datetime,
    indexer: NoteIndexerProtocol | None,
    daily_folder_name: str | None,
) -> NoteFlowOutcome:
    """Write the dictated note and its surroundings; degrade honestly.

    ``body_markdown`` is the cleaned text (or the raw text when cleanup
    fell back); ``verbatim_text`` is ALWAYS retained inside the note by the
    writer when it differs from the body (fidelity mandate).
    """
    title = await resolve_dictation_note_title(route, verbatim_text, now)
    note_path = create_inbox_dictation_note(
        vault_root,
        title=title.title,
        body_markdown=body_markdown,
        date_iso=now.strftime("%Y-%m-%d"),
        # Raw retained byte-identical whenever the body is a cleaned rewrite.
        raw_verbatim=verbatim_text if body_markdown != verbatim_text else None,
    )
    degraded = await _index_note(indexer, note_path)
    daily_degraded = _append_daily_line(vault_root, now, note_path, daily_folder_name)
    reasons = "; ".join(r for r in (degraded, daily_degraded) if r) or None
    return NoteFlowOutcome(
        note_path=str(note_path),
        note_title=title.title,
        title_source=title.source,
        provider=title.provider,
        model=title.model,
        latency_ms=title.latency_ms,
        degraded_reason=reasons,
    )


async def _index_note(indexer: NoteIndexerProtocol | None, note_path: Path) -> str | None:
    """Incremental index of the new note; failure degrades honestly."""
    if indexer is None:
        return "index not wired; note saved but not yet searchable"
    try:
        await indexer.index_changed_files([note_path])
    except Exception as exc:
        logger.exception("dictation note indexing failed; note is saved")
        return f"indexing failed: {exc}"
    return None


def _append_daily_line(
    vault_root: Path, now: datetime, note_path: Path, daily_folder_name: str | None
) -> str | None:
    """One-line daily log entry; failure degrades honestly."""
    line = f"- {now.strftime('%H:%M')} dictated [[{note_path.stem}]]"
    try:
        if daily_folder_name is None:
            append_daily_note_line(vault_root, date_iso=now.strftime("%Y-%m-%d"), line=line)
        else:
            append_daily_note_line(
                vault_root,
                date_iso=now.strftime("%Y-%m-%d"),
                line=line,
                daily_folder_name=daily_folder_name,
            )
    except Exception as exc:
        logger.exception("daily-note line append failed; note is saved")
        return f"daily note line failed: {exc}"
    return None
