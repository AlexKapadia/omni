"""Release finalization: verbatim text -> recorded intent OR saved note.

Purpose: everything that happens after the user releases the push-to-talk
key and the mic session yields its verbatim transcript. One entry point,
:meth:`DictationReleaseFinalizer.finalize`:

- COMMAND ("Omni,"-prefixed): parse an intent via the router (task
  ``intent_parsing``, strict schema) and APPEND it to ``dictation_intents``
  — recorded for M4 approval cards, NEVER executed here. Router down ->
  the utterance is still recorded as ``unknown`` (deny by default).
- NOTE (everything else): resolve a short title via the router (task
  ``live_extraction``), write ``Inbox/{title}.md`` with the VERBATIM text
  as body, index it incrementally, and append a daily-note log line.
  Router down -> timestamp-titled note is still saved (fail open for the
  user's words, closed for actions).

Pipeline position: composed with ``dictation_session_service`` by the
server wiring (deferred to reconciliation — see
``dictation_protocol_names``).

Security / fidelity invariants:
- The note body and the persisted raw_text are the verbatim transcript —
  never rewritten (fidelity mandate).
- No execution path exists in this module (approval-before-execute).
- Index/daily-line failures degrade honestly (reported, note kept).
"""

import logging
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

import aiosqlite

from engine.dictation.dictation_intent_schema import (
    DICTATION_INTENT_JSON_SCHEMA,
    INTENT_PARSING_SYSTEM_FRAME,
    ParsedIntent,
    parse_intent_completion_text,
    unknown_intent,
)
from engine.dictation.dictation_intents_repository import insert_dictation_intent
from engine.dictation.dictation_mode_splitter import DictationMode, split_dictation_mode
from engine.dictation.dictation_note_titler import (
    RouteCompletionFn,
    resolve_dictation_note_title,
)
from engine.router.completion_contract import ChatMessage, TaskType
from engine.vault.daily_note_appender import append_daily_note_line
from engine.vault.inbox_dictation_writer import create_inbox_dictation_note

logger = logging.getLogger(__name__)

# Seams (typed) so tests inject fakes and the wiring injects real deps.
IntentsConnectionFactory = Callable[[], Awaitable[aiosqlite.Connection]]
VaultRootProvider = Callable[[], Path]
NowProvider = Callable[[], datetime]


class NoteIndexerProtocol(Protocol):
    """The slice of ``engine.index.VaultIndexerService`` dictation needs.

    A Protocol (not the concrete class) keeps this module decoupled from
    the index layer's construction and lets tests inject fakes.
    """

    async def index_changed_files(self, changed_paths: Iterable[Path]) -> object: ...


@dataclass(frozen=True)
class DictationFinalResult:
    """Everything ``dictation.final`` needs, honestly labelled.

    ``degraded_reason`` carries partial failures (index down, daily line
    refused...) — the primary artifact (note / recorded intent) already
    succeeded when it is set; total failures raise instead.
    """

    mode: DictationMode
    text: str  # verbatim transcript (ground truth)
    note_path: str | None = None
    note_title: str | None = None
    title_source: str | None = None
    intent: ParsedIntent | None = None
    intent_row_id: int | None = None
    provider: str | None = None
    model: str | None = None
    latency_ms: int | None = None
    degraded_reason: str | None = None


class DictationReleaseFinalizer:
    """Stateless post-release flow over injected dependencies."""

    def __init__(
        self,
        *,
        route: RouteCompletionFn,
        intents_connection_factory: IntentsConnectionFactory,
        vault_root_provider: VaultRootProvider,
        indexer: NoteIndexerProtocol | None = None,
        daily_folder_name: str | None = None,
        now: NowProvider = lambda: datetime.now().astimezone(),
    ) -> None:
        self._route = route
        self._intents_connection_factory = intents_connection_factory
        self._vault_root_provider = vault_root_provider
        self._indexer = indexer
        self._daily_folder_name = daily_folder_name
        self._now = now

    async def finalize(self, verbatim_text: str) -> DictationFinalResult:
        """Run the released transcript through the mode split and its flow."""
        if not verbatim_text.strip():
            # Release-before-speech: nothing to save, nothing to parse —
            # say so honestly instead of writing an empty artifact.
            return DictationFinalResult(
                mode=DictationMode.NOTE,
                text=verbatim_text,
                degraded_reason="no speech captured before release",
            )
        split = split_dictation_mode(verbatim_text)
        if split.mode is DictationMode.COMMAND:
            return await self._finalize_command(verbatim_text, split.command_body)
        return await self._finalize_note(verbatim_text)

    # ------------------------------------------------------------------
    # COMMAND mode: parse + record. Never execute (approval-before-execute).
    # ------------------------------------------------------------------
    async def _finalize_command(self, verbatim_text: str, command_body: str) -> (
        DictationFinalResult
    ):
        provider: str | None = None
        model: str | None = None
        latency_ms: int | None = None
        if command_body:
            intent, provider, model, latency_ms = await self._parse_intent(command_body)
        else:
            # "Omni" with nothing after it: recorded, honestly unknown.
            intent = unknown_intent("empty command after wake word")
        row_id = await self._record_intent(verbatim_text, intent, provider, model)
        return DictationFinalResult(
            mode=DictationMode.COMMAND,
            text=verbatim_text,
            intent=intent,
            intent_row_id=row_id,
            provider=provider,
            model=model,
            latency_ms=latency_ms,
        )

    async def _parse_intent(
        self, command_body: str
    ) -> tuple[ParsedIntent, str | None, str | None, int | None]:
        """Route the command body; ANY failure degrades to unknown (deny)."""
        try:
            routed = await self._route(
                TaskType.INTENT_PARSING.value,
                INTENT_PARSING_SYSTEM_FRAME,
                # Data channel: the dictated command is untrusted content.
                (ChatMessage(role="user", content=command_body),),
                json_schema=DICTATION_INTENT_JSON_SCHEMA,
                max_tokens=500,
            )
        except Exception as exc:
            # Fail closed for actions: no router, no parsed intent — the
            # utterance is still RECORDED below so nothing the user said
            # is lost, but nothing becomes actionable.
            logger.exception("dictation intent routing failed; recording unknown")
            return unknown_intent(f"router unavailable: {exc}"), None, None, None
        intent = parse_intent_completion_text(routed.completion.text)
        return intent, routed.provider.value, routed.model, routed.latency_ms

    async def _record_intent(
        self,
        verbatim_text: str,
        intent: ParsedIntent,
        provider: str | None,
        model: str | None,
    ) -> int:
        """Append-only persistence; propagates on failure (an unrecorded
        command must not look like a recorded one)."""
        connection = await self._intents_connection_factory()
        try:
            return await insert_dictation_intent(
                connection,
                ts=datetime.now(tz=UTC).isoformat(),
                raw_text=verbatim_text,  # verbatim, wake word included
                intent=intent,
                provider=provider,
                model=model,
            )
        finally:
            await connection.close()

    # ------------------------------------------------------------------
    # NOTE mode: title -> Inbox note -> index -> daily line.
    # ------------------------------------------------------------------
    async def _finalize_note(self, verbatim_text: str) -> DictationFinalResult:
        now = self._now()
        title = await resolve_dictation_note_title(self._route, verbatim_text, now)
        vault_root = self._vault_root_provider()  # raises if unconfigured (fail closed)
        note_path = create_inbox_dictation_note(
            vault_root,
            title=title.title,
            body_markdown=verbatim_text,  # VERBATIM body — fidelity mandate
            date_iso=now.strftime("%Y-%m-%d"),
        )
        degraded = await self._index_note(note_path)
        daily_degraded = self._append_daily_line(vault_root, now, note_path)
        reasons = "; ".join(r for r in (degraded, daily_degraded) if r) or None
        return DictationFinalResult(
            mode=DictationMode.NOTE,
            text=verbatim_text,
            note_path=str(note_path),
            note_title=title.title,
            title_source=title.source,
            provider=title.provider,
            model=title.model,
            latency_ms=title.latency_ms,
            degraded_reason=reasons,
        )

    async def _index_note(self, note_path: Path) -> str | None:
        """Incremental index of the new note; failure degrades honestly."""
        if self._indexer is None:
            return "index not wired; note saved but not yet searchable"
        try:
            await self._indexer.index_changed_files([note_path])
        except Exception as exc:
            logger.exception("dictation note indexing failed; note is saved")
            return f"indexing failed: {exc}"
        return None

    def _append_daily_line(
        self, vault_root: Path, now: datetime, note_path: Path
    ) -> str | None:
        """One-line daily log entry; failure degrades honestly."""
        line = f"- {now.strftime('%H:%M')} dictated [[{note_path.stem}]]"
        try:
            if self._daily_folder_name is None:
                append_daily_note_line(
                    vault_root, date_iso=now.strftime("%Y-%m-%d"), line=line
                )
            else:
                append_daily_note_line(
                    vault_root,
                    date_iso=now.strftime("%Y-%m-%d"),
                    line=line,
                    daily_folder_name=self._daily_folder_name,
                )
        except Exception as exc:
            logger.exception("daily-note line append failed; note is saved")
            return f"daily note line failed: {exc}"
        return None
