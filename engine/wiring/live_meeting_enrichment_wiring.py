"""Server wiring: capture lifecycle -> live summary + proactive vault poll.

Subscribes to ``transcript.final`` via the hub; one async worker per meeting
runs enrichment off the transcription hot path.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from pathlib import Path
from typing import Protocol

import aiosqlite

from engine.ask.ask_answer_contracts import LiveAnswerSource
from engine.ask.live_summary_service import LiveSummaryService
from engine.ask.live_translation_service import LiveTranslationService, TranslationEmitter
from engine.ask.proactive_vault_poller import ProactiveVaultPoller
from engine.index import HybridRrfRetriever
from engine.protocol import (
    EVENT_CAPTURE_STARTED,
    EVENT_CAPTURE_STOPPED,
    EVENT_TRANSCRIPT_FINAL,
    Envelope,
    EnvelopeKind,
    EventBroadcastHub,
)
from engine.protocol.live_enrichment_payloads import (
    SUMMARY_UPDATED_EVENT_NAME,
    TRANSLATION_UPDATED_EVENT_NAME,
    VAULT_SUGGESTION_EVENT_NAME,
    summary_updated_payload,
    translation_updated_payload,
    vault_suggestion_payload,
)
from engine.router import (
    ProviderRouter,
    RouterLedgerEntry,
    build_provider_clients,
    insert_router_ledger_entry,
)
from engine.security import ProviderKeyStore
from engine.storage.app_settings_repository import (
    SETTING_LIVE_TRANSLATION_LANG,
    SETTING_SUMMARY_MODEL_ID,
    SETTING_SUMMARY_PROVIDER,
    read_setting,
)
from engine.storage.sqlite_connection import open_sqlite_connection
from engine.storage.sqlite_migrations_runner import apply_migrations
from engine.wiring.combined_enrichment_session import CombinedEnrichmentSession

logger = logging.getLogger(__name__)

_FLUSH_AND_STOP = object()


class EnrichmentSessionProtocol(Protocol):
    async def on_final_segment(self, stream: str, text: str) -> None: ...
    async def tick(self) -> None: ...
    async def flush(self) -> None: ...


class LiveMeetingEnrichmentWiring:
    """One per engine process; construction is inert."""

    def __init__(
        self,
        hub: EventBroadcastHub,
        db_path: Path,
        migrations_dir: Path,
    ) -> None:
        self._hub = hub
        self._db_path = db_path
        self._migrations_dir = migrations_dir
        self._connection: aiosqlite.Connection | None = None
        self._queue: asyncio.Queue[object] | None = None
        self._worker: asyncio.Task[None] | None = None
        self._tick_task: asyncio.Task[None] | None = None
        self._unsubscribe = hub.subscribe(self._on_event)
        self._translation: LiveTranslationService | None = None
        # Late-attach seams: session may start with empty lang; settings can
        # enable translation mid-meeting — need router/emit from session start.
        self._session_router: ProviderRouter | None = None
        self._session_emit_translation: TranslationEmitter | None = None
        self._session_preferred_model: str | None = None
        self._session_preferred_provider: str | None = None
        self._combined: CombinedEnrichmentSession | None = None

    def apply_translation_lang(self, effective: dict[str, object]) -> None:
        """Hot-reload live_translation_lang onto the active session service."""
        raw = effective.get(SETTING_LIVE_TRANSLATION_LANG)
        lang = raw.strip() if isinstance(raw, str) else ""
        if self._translation is not None:
            self._translation.set_target_lang(lang)
            return
        if not lang:
            return
        router = self._session_router
        emit = self._session_emit_translation
        if router is None or emit is None:
            return
        translation = LiveTranslationService(
            router,
            emit,
            lang,
            preferred_model=self._session_preferred_model,
            preferred_provider=self._session_preferred_provider,
        )
        self._translation = translation
        if self._combined is not None:
            self._combined._translation = translation

    async def _on_event(self, envelope: Envelope) -> None:
        try:
            if envelope.kind is not EnvelopeKind.EVENT:
                return
            if envelope.name == EVENT_CAPTURE_STARTED:
                payload = envelope.payload
                mid = payload.get("meeting_id")
                if isinstance(mid, str):
                    await self._start_session(mid)
            elif envelope.name == EVENT_TRANSCRIPT_FINAL:
                self._enqueue_segment(envelope.payload)
            elif envelope.name == EVENT_CAPTURE_STOPPED and self._queue is not None:
                self._queue.put_nowait(_FLUSH_AND_STOP)
        except Exception:
            logger.exception("live enrichment wiring failed handling %s", envelope.name)

    async def _start_session(self, meeting_id: str) -> None:
        await self.shutdown_session()
        await apply_migrations(self._db_path, self._migrations_dir)
        connection = await open_sqlite_connection(self._db_path)
        retriever = HybridRrfRetriever(connection, None, None)

        async def record(entry: RouterLedgerEntry) -> None:
            await insert_router_ledger_entry(connection, entry)

        router = ProviderRouter(build_provider_clients(ProviderKeyStore()), record)

        async def emit_summary(summary_md: str, updated_at_ms: int) -> None:
            await self._hub.broadcast_event(
                SUMMARY_UPDATED_EVENT_NAME,
                summary_updated_payload(meeting_id, summary_md, updated_at_ms),
            )

        async def emit_vault(
            topic: str, sources: tuple[LiveAnswerSource, ...], latency_ms: int
        ) -> None:
            hits = [
                {
                    "note_path": s.note_path,
                    "line_start": s.line_start,
                    "line_end": s.line_end,
                    "heading_path": s.heading_path,
                    "snippet": s.snippet,
                    "score": s.score,
                }
                for s in sources
            ]
            await self._hub.broadcast_event(
                VAULT_SUGGESTION_EVENT_NAME,
                vault_suggestion_payload(topic, hits, latency_ms),
            )

        summary_model_raw = await read_setting(connection, SETTING_SUMMARY_MODEL_ID)
        preferred_model = summary_model_raw if isinstance(summary_model_raw, str) else None
        summary_provider_raw = await read_setting(connection, SETTING_SUMMARY_PROVIDER)
        preferred_provider = (
            summary_provider_raw if isinstance(summary_provider_raw, str) else None
        )
        summary = LiveSummaryService(
            router,
            emit_summary,
            preferred_model=preferred_model,
            preferred_provider=preferred_provider,
        )
        vault = ProactiveVaultPoller(connection, retriever, emit_vault)

        async def emit_translation(lines: list[dict[str, object]]) -> None:
            await self._hub.broadcast_event(
                TRANSLATION_UPDATED_EVENT_NAME,
                translation_updated_payload(lines),
            )

        raw_lang = await read_setting(connection, SETTING_LIVE_TRANSLATION_LANG)
        target_lang = raw_lang.strip() if isinstance(raw_lang, str) else ""
        translation: LiveTranslationService | None = None
        if target_lang:
            translation = LiveTranslationService(
                router,
                emit_translation,
                target_lang,
                preferred_model=preferred_model,
                preferred_provider=preferred_provider,
            )
        self._session_router = router
        self._session_emit_translation = emit_translation
        self._session_preferred_model = preferred_model
        self._session_preferred_provider = preferred_provider
        self._translation = translation
        session = CombinedEnrichmentSession(summary, vault, translation)
        self._combined = session

        queue: asyncio.Queue[object] = asyncio.Queue()
        self._connection = connection
        self._queue = queue
        self._worker = asyncio.get_running_loop().create_task(
            self._run_worker(session, queue), name="live-enrichment-worker"
        )
        self._tick_task = asyncio.get_running_loop().create_task(
            self._tick_loop(session), name="live-enrichment-ticker"
        )

    def _enqueue_segment(self, payload: dict[str, object]) -> None:
        if self._queue is None:
            return
        stream = payload.get("stream")
        text = payload.get("text")
        if isinstance(stream, str) and isinstance(text, str) and text.strip():
            self._queue.put_nowait((stream, text))

    async def _tick_loop(self, session: EnrichmentSessionProtocol) -> None:
        try:
            while True:
                await asyncio.sleep(5.0)
                if self._queue is None:
                    break
                await session.tick()
        except asyncio.CancelledError:
            return

    async def _run_worker(
        self, session: EnrichmentSessionProtocol, queue: asyncio.Queue[object]
    ) -> None:
        while True:
            item = await queue.get()
            try:
                if item is _FLUSH_AND_STOP:
                    # Stop the ticker before closing sqlite so tick() cannot
                    # race against a closed connection (unretrieved exception).
                    await self._cancel_tick_task()
                    await session.flush()
                    break
                if isinstance(item, tuple):
                    stream, text = item
                    await session.on_final_segment(stream, text)
            except Exception:
                logger.exception("live enrichment pass failed")
                if item is _FLUSH_AND_STOP:
                    await self._cancel_tick_task()
                    break
        await self._close_connection()

    async def _cancel_tick_task(self) -> None:
        """Cancel the 5s ticker; safe to call more than once."""
        tick, self._tick_task = self._tick_task, None
        if tick is not None and not tick.done():
            tick.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await tick

    async def _close_connection(self) -> None:
        connection, self._connection = self._connection, None
        self._queue = None
        if connection is not None:
            with contextlib.suppress(Exception):
                await connection.close()

    async def shutdown_session(self) -> None:
        self._translation = None
        self._session_router = None
        self._session_emit_translation = None
        self._session_preferred_model = None
        self._session_preferred_provider = None
        self._combined = None
        await self._cancel_tick_task()
        worker, self._worker = self._worker, None
        if worker is not None and not worker.done():
            worker.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await worker
        await self._close_connection()

    async def shutdown(self) -> None:
        self._unsubscribe()
        await self.shutdown_session()
