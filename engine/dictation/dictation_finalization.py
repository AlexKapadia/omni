"""Release finalization: verbatim text -> intent, saved note, or injection.

Purpose: everything that happens after the user releases the push-to-talk
key and the mic session yields its verbatim transcript. One entry point,
:meth:`DictationReleaseFinalizer.finalize`:

- COMMAND ("Omni,"-prefixed — always wins): parse an intent via the router
  (task ``intent_parsing``, strict schema) and APPEND it to
  ``dictation_intents`` — recorded for M4 approval cards, NEVER executed
  here. Router down -> the utterance is still recorded as ``unknown``.
- INJECT (UI-requested: an external app was focused at keydown): clean the
  raw text (task ``dictation_cleanup``, faithfulness-guarded) and return
  it for the shell to paste into the focused app. No note is written —
  the text lands where the user is typing, like a keyboard would.
- NOTE (the default): clean the text, resolve a short title (task
  ``live_extraction``), write ``Inbox/{title}.md`` with the CLEANED body
  and the RAW transcript retained byte-identical, index it, and append a
  daily-note log line (flow lives in ``dictation_note_flow``).

Pipeline position: composed with ``dictation_session_service`` by the
server wiring (deferred to reconciliation — see
``dictation_protocol_names``).

Security / fidelity invariants:
- ``text`` is ALWAYS the raw verbatim transcript (ground truth); cleanup
  produces the SEPARATE ``cleaned_text`` and any cleanup failure degrades
  to the raw text — the user's words never fail on cloud health.
- No execution path exists in this module (approval-before-execute).
- The wake word beats the inject hint: a command can never be pasted.
"""

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import aiosqlite

from engine.dictation.dictation_history_repository import insert_dictation_entry
from engine.storage.app_settings_repository import SETTING_STT_ENGINE, read_setting
from engine.dictation.dictation_cleanup import CleanupResult, clean_dictation_text
from engine.dictation.dictation_intent_schema import (
    DICTATION_INTENT_JSON_SCHEMA,
    INTENT_PARSING_SYSTEM_FRAME,
    ParsedIntent,
    parse_intent_completion_text,
    unknown_intent,
)
from engine.dictation.dictation_intents_repository import insert_dictation_intent
from engine.dictation.dictation_mode_splitter import DictationMode, split_dictation_mode
from engine.dictation.dictation_note_flow import NoteIndexerProtocol, persist_dictation_note
from engine.dictation.dictation_note_titler import RouteCompletionFn
from engine.dictation.personal_dictionary import PersonalDictionary
from engine.router.completion_contract import ChatMessage, TaskType

logger = logging.getLogger(__name__)

# Seams (typed) so tests inject fakes and the wiring injects real deps.
IntentsConnectionFactory = Callable[[], Awaitable[aiosqlite.Connection]]
VaultRootProvider = Callable[[], Path]
NowProvider = Callable[[], datetime]

__all__ = [
    "DictationFinalResult",
    "DictationReleaseFinalizer",
    "IntentsConnectionFactory",
    "NoteIndexerProtocol",
    "NowProvider",
    "VaultRootProvider",
]


@dataclass(frozen=True)
class DictationFinalResult:
    """Everything ``dictation.final`` needs, honestly labelled.

    ``text`` is the raw verbatim transcript (ground truth, always).
    ``cleaned_text`` / ``cleanup_source`` / ``cleanup_latency_ms`` are the
    additive cleanup fields: present for NOTE and INJECT modes;
    ``cleaned_text`` equals the raw text when cleanup fell back (source
    ``raw_fallback``). ``flush_ms`` is the wiring-measured STT flush time
    (speed-showcase mandate). ``degraded_reason`` carries partial failures
    — the primary artifact already succeeded when it is set.
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
    cleaned_text: str | None = None
    cleanup_source: str | None = None
    cleanup_latency_ms: int | None = None
    flush_ms: int | None = None


class DictationReleaseFinalizer:
    """Stateless post-release flow over injected dependencies."""

    def __init__(
        self,
        *,
        route: RouteCompletionFn,
        intents_connection_factory: IntentsConnectionFactory,
        vault_root_provider: VaultRootProvider,
        cleanup_style: str = "classic",
        indexer: NoteIndexerProtocol | None = None,
        daily_folder_name: str | None = None,
        now: NowProvider = lambda: datetime.now().astimezone(),
        dictionary: PersonalDictionary | None = None,
    ) -> None:
        self._route = route
        self._intents_connection_factory = intents_connection_factory
        self._cleanup_style = cleanup_style
        self._vault_root_provider = vault_root_provider
        self._indexer = indexer
        self._daily_folder_name = daily_folder_name
        self._now = now
        # Personal spelling dictionary: fail-open by construction (missing
        # file / non-Windows env -> empty vocabulary, never an error).
        self._dictionary = dictionary if dictionary is not None else PersonalDictionary()

    async def finalize(
        self,
        verbatim_text: str,
        *,
        inject_requested: bool = False,
        flush_ms: int | None = None,
    ) -> DictationFinalResult:
        """Run the released transcript through the mode split and its flow.

        ``inject_requested`` is the UI's disposition hint (external app
        focused at keydown, not flipped to note before release). The wake
        word is authoritative: COMMAND beats the hint unconditionally.
        """
        if not verbatim_text.strip():
            # Release-before-speech: nothing to save, parse, or paste —
            # say so honestly instead of producing an empty artifact.
            return DictationFinalResult(
                mode=DictationMode.NOTE,
                text=verbatim_text,
                degraded_reason="no speech captured before release",
                flush_ms=flush_ms,
            )
        split = split_dictation_mode(verbatim_text)
        if split.mode is DictationMode.COMMAND:
            final = await self._finalize_command(verbatim_text, split.command_body, flush_ms)
        elif inject_requested:
            final = await self._finalize_inject(verbatim_text, flush_ms)
        else:
            final = await self._finalize_note(verbatim_text, flush_ms)
        return final

    # ------------------------------------------------------------------
    # COMMAND mode: parse + record. Never execute (approval-before-execute).
    # ------------------------------------------------------------------
    async def _finalize_command(
        self, verbatim_text: str, command_body: str, flush_ms: int | None
    ) -> DictationFinalResult:
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
            flush_ms=flush_ms,
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
    # Shared cleanup step (INJECT + NOTE): raw -> cleaned, raw retained.
    # ------------------------------------------------------------------
    async def _run_cleanup(self, verbatim_text: str) -> CleanupResult:
        """Faithfulness-guarded cleanup; NEVER raises (raw fallback inside)."""
        return await clean_dictation_text(
            self._route,
            verbatim_text,
            self._dictionary.terms(),
            style=self._cleanup_style,
        )

    async def record_history_entry(
        self,
        connection: aiosqlite.Connection,
        result: DictationFinalResult,
    ) -> None:
        if not result.text.strip():
            return
        stt_engine = await read_setting(connection, SETTING_STT_ENGINE)
        await insert_dictation_entry(
            connection,
            created_at_iso=datetime.now(tz=UTC).isoformat(),
            mode=result.mode.value,
            raw_text=result.text,
            cleaned_text=result.cleaned_text,
            note_path=result.note_path,
            note_title=result.note_title,
            cleanup_style=self._cleanup_style,
            stt_engine=stt_engine if isinstance(stt_engine, str) else None,
        )

    # ------------------------------------------------------------------
    # INJECT mode: cleaned text for the shell to paste. No note, no action.
    # ------------------------------------------------------------------
    async def _finalize_inject(
        self, verbatim_text: str, flush_ms: int | None
    ) -> DictationFinalResult:
        cleanup = await self._run_cleanup(verbatim_text)
        return DictationFinalResult(
            mode=DictationMode.INJECT,
            text=verbatim_text,  # raw retained even though cleaned is pasted
            provider=cleanup.provider,
            model=cleanup.model,
            latency_ms=cleanup.latency_ms,
            degraded_reason=cleanup.degraded_reason,
            cleaned_text=cleanup.cleaned_text,
            cleanup_source=cleanup.source,
            cleanup_latency_ms=cleanup.latency_ms,
            flush_ms=flush_ms,
        )

    # ------------------------------------------------------------------
    # NOTE mode: cleanup -> title -> Inbox note (raw kept) -> index -> daily.
    # ------------------------------------------------------------------
    async def _finalize_note(
        self, verbatim_text: str, flush_ms: int | None
    ) -> DictationFinalResult:
        cleanup = await self._run_cleanup(verbatim_text)
        now = self._now()
        vault_root = self._vault_root_provider()  # raises if unconfigured (fail closed)
        outcome = await persist_dictation_note(
            route=self._route,
            vault_root=vault_root,
            verbatim_text=verbatim_text,
            body_markdown=cleanup.cleaned_text,
            now=now,
            indexer=self._indexer,
            daily_folder_name=self._daily_folder_name,
        )
        reasons = "; ".join(
            r for r in (cleanup.degraded_reason, outcome.degraded_reason) if r
        ) or None
        return DictationFinalResult(
            mode=DictationMode.NOTE,
            text=verbatim_text,
            note_path=outcome.note_path,
            note_title=outcome.note_title,
            title_source=outcome.title_source,
            provider=outcome.provider,
            model=outcome.model,
            latency_ms=outcome.latency_ms,
            degraded_reason=reasons,
            cleaned_text=cleanup.cleaned_text,
            cleanup_source=cleanup.source,
            cleanup_latency_ms=cleanup.latency_ms,
            flush_ms=flush_ms,
        )
