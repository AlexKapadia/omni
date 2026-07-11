"""Server wiring: capture lifecycle -> LiveAnswersSpotter -> ``answers.hit``.

Purpose: connects M3's live answers spotter to the running capture session
per the deferred spec in ``engine/ask/__init__``: a spotter is constructed
at ``capture.started``, fed every ``transcript.final`` segment, flushed at
``capture.stopped``, and its hits broadcast as ``answers.hit`` events.
Pipeline position: subscribed to the ``EventBroadcastHub`` beside the WS
connection handlers; sits above ``engine.ask`` / ``engine.index`` /
``engine.router``.

Design: the hub delivers events INLINE on the transcription path, so this
wiring only ENQUEUES work there; a per-meeting worker task runs the
spotter's router/retrieval calls so live transcription never stalls behind
an answers pass.

Security / resilience invariants:
- The hub subscriber NEVER raises (a raising subscriber gets dropped by
  the hub — live answers must not disconnect itself, let alone others).
- Spotter failures degrade to silence; capture is untouched (the spotter's
  own contract, upheld again here around the worker loop).
- Dense retrieval stays an explicit BM25-only degradation until the vec
  model ships (same documented decision as the ask gateway).
"""

import asyncio
import contextlib
import logging
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Protocol

import aiosqlite

from engine.ask import ANSWERS_HIT_EVENT_NAME, LiveAnswersSpotter, answer_hit_to_payload
from engine.ask.ask_answer_contracts import LiveAnswerHit
from engine.index import HybridRrfRetriever
from engine.protocol import (
    EVENT_CAPTURE_STARTED,
    EVENT_CAPTURE_STOPPED,
    EVENT_TRANSCRIPT_FINAL,
    Envelope,
    EnvelopeKind,
    EventBroadcastHub,
)
from engine.router import (
    ProviderRouter,
    RouterLedgerEntry,
    build_provider_clients,
    insert_router_ledger_entry,
)
from engine.security import ProviderKeyStore
from engine.storage.sqlite_connection import open_sqlite_connection
from engine.storage.sqlite_migrations_runner import apply_migrations

logger = logging.getLogger(__name__)

HitEmitter = Callable[[LiveAnswerHit], Awaitable[None]]


class SpotterProtocol(Protocol):
    """The slice of ``LiveAnswersSpotter`` the wiring drives (tests fake it)."""

    async def on_final_segment(self, stream: str, text: str) -> None: ...

    async def flush(self) -> None: ...


# Builds the per-meeting spotter over the meeting's own connection.
SpotterFactory = Callable[[aiosqlite.Connection, HitEmitter], SpotterProtocol]

# Worker-queue sentinel: capture stopped -> flush, then shut the session down.
_FLUSH_AND_STOP = object()


class LiveAnswersSpotterWiring:
    """One per engine process; construction is inert (no keys, no I/O)."""

    def __init__(
        self,
        hub: EventBroadcastHub,
        db_path: Path,
        migrations_dir: Path,
        spotter_factory: SpotterFactory | None = None,
    ) -> None:
        self._hub = hub
        self._db_path = db_path
        self._migrations_dir = migrations_dir
        # None → async default builder (reads summary Settings); tests inject fakes.
        self._spotter_factory = spotter_factory
        # Per-meeting session state (None while idle).
        self._connection: aiosqlite.Connection | None = None
        self._queue: asyncio.Queue[object] | None = None
        self._worker: asyncio.Task[None] | None = None
        # The hub hands us our own broadcasts too; subscribe() returns the
        # unsubscribe used at shutdown.
        self._unsubscribe = hub.subscribe(self._on_event)

    async def _build_default_spotter(
        self, connection: aiosqlite.Connection, emit: HitEmitter
    ) -> SpotterProtocol:
        """Real spotter: BM25 retrieval + keyed router, ledger-bound.

        Reads summary Settings so live_extraction honour preferred_provider
        / preferred_model (Ollama-first) the same way ask/enhance do.
        """
        from engine.storage.app_settings_repository import (
            SETTING_SUMMARY_MODEL_ID,
            SETTING_SUMMARY_PROVIDER,
            read_setting,
        )

        retriever = HybridRrfRetriever(connection, None, None)  # BM25-only (documented)

        async def record(entry: RouterLedgerEntry) -> None:
            # Append-only ledger row per external call (audit invariant).
            await insert_router_ledger_entry(connection, entry)

        router = ProviderRouter(build_provider_clients(ProviderKeyStore()), record)
        summary_model_raw = await read_setting(connection, SETTING_SUMMARY_MODEL_ID)
        preferred_model = summary_model_raw if isinstance(summary_model_raw, str) else None
        summary_provider_raw = await read_setting(connection, SETTING_SUMMARY_PROVIDER)
        preferred_provider = (
            summary_provider_raw if isinstance(summary_provider_raw, str) else None
        )
        return LiveAnswersSpotter(
            connection,
            retriever,
            router,
            emit,
            preferred_model=preferred_model,
            preferred_provider=preferred_provider,
        )

    async def _on_event(self, envelope: Envelope) -> None:
        """Hub subscriber: cheap routing only; NEVER raises (see docstring)."""
        try:
            if envelope.kind is not EnvelopeKind.EVENT:
                return
            if envelope.name == EVENT_CAPTURE_STARTED:
                await self._start_session()
            elif envelope.name == EVENT_TRANSCRIPT_FINAL:
                self._enqueue_segment(envelope.payload)
            elif envelope.name == EVENT_CAPTURE_STOPPED and self._queue is not None:
                self._queue.put_nowait(_FLUSH_AND_STOP)
        except Exception:
            # Live answers degrade to silence; the broadcast path stays alive.
            logger.exception("live answers wiring failed handling %s", envelope.name)

    async def _start_session(self) -> None:
        """New meeting: fresh connection, fresh spotter, fresh worker."""
        await self.shutdown_session()  # A hanging previous session never leaks.
        await apply_migrations(self._db_path, self._migrations_dir)
        connection = await open_sqlite_connection(self._db_path)
        if self._spotter_factory is not None:
            spotter = self._spotter_factory(connection, self._emit_hit)
        else:
            spotter = await self._build_default_spotter(connection, self._emit_hit)
        queue: asyncio.Queue[object] = asyncio.Queue()
        self._connection = connection
        self._queue = queue
        self._worker = asyncio.get_running_loop().create_task(
            self._run_worker(spotter, queue), name="live-answers-spotter-worker"
        )

    def _enqueue_segment(self, payload: dict[str, object]) -> None:
        """transcript.final -> queue. Type-guarded; malformed frames are skipped."""
        if self._queue is None:
            return  # final arriving outside a session: nothing to feed
        stream = payload.get("stream")
        text = payload.get("text")
        if isinstance(stream, str) and isinstance(text, str) and text.strip():
            self._queue.put_nowait((stream, text))

    async def _emit_hit(self, hit: LiveAnswerHit) -> None:
        """Spotter emit callback -> the pinned ``answers.hit`` broadcast."""
        await self._hub.broadcast_event(ANSWERS_HIT_EVENT_NAME, answer_hit_to_payload(hit))

    async def _run_worker(self, spotter: SpotterProtocol, queue: asyncio.Queue[object]) -> None:
        """Drain segments into the spotter off the transcription path."""
        while True:
            item = await queue.get()
            try:
                if item is _FLUSH_AND_STOP:
                    await spotter.flush()  # spot whatever the meeting left buffered
                    break
                if isinstance(item, tuple):  # queue carries (stream, text) pairs
                    stream, text = item
                    await spotter.on_final_segment(stream, text)
            except Exception:
                # One bad pass must not end live answers for the meeting.
                logger.exception("live answers spotter pass failed")
                if item is _FLUSH_AND_STOP:
                    break
        await self._close_connection()

    async def _close_connection(self) -> None:
        connection, self._connection = self._connection, None
        self._queue = None
        if connection is not None:
            with contextlib.suppress(Exception):
                await connection.close()

    async def shutdown_session(self) -> None:
        """Tear down any live session (idempotent; leaves no orphan task)."""
        worker, self._worker = self._worker, None
        if worker is not None and not worker.done():
            worker.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await worker
        await self._close_connection()

    async def shutdown(self) -> None:
        """Process shutdown: unsubscribe from the hub and stop the session."""
        self._unsubscribe()
        await self.shutdown_session()
