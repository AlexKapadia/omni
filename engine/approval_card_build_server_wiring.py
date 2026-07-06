"""Server wiring: source-row seams -> PENDING approval cards -> ``card.updated``.

Purpose: connects M4's card BUILDERS to the two places source rows are
born, without restructuring either producer:
- Meeting finalization: subscribed to the hub's ``enhance.ready`` /
  ``enhance.failed`` events (the finalization service's own outcome
  broadcast). The DB — not the event name — decides: cards are built only
  when ``meetings.finalized_at`` is set, because ``enhance.failed`` also
  fires for refused runs and for finalized-but-unenhanced runs (whose
  extraction may still have succeeded).
- Dictation command intents: :meth:`on_dictation_final` is handed to the
  dictation gateway as its post-release hook; a recorded intent row becomes
  at most one pending card.
Pipeline position: subscribed to the ``EventBroadcastHub`` beside the WS
connection handlers; sits above ``engine.agents`` / ``engine.storage``.

Security invariants:
- SUGGEST-ONLY: this wiring inserts PENDING cards and broadcasts them —
  nothing here approves or executes anything (approval-before-execute).
- The hub subscriber NEVER raises (a raising subscriber gets dropped);
  builder failures degrade to a log line, never a lost finalization.
"""

import asyncio
import contextlib
import logging
from collections.abc import Coroutine
from datetime import UTC, datetime
from pathlib import Path

import aiosqlite

from engine.agents.approval_card_builder import build_cards_from_extraction
from engine.agents.approval_cards_repository import get_card
from engine.agents.approval_protocol_names import (
    CARD_UPDATED_EVENT_NAME,
    build_card_updated_payload,
)
from engine.agents.dictation_intent_card_builder import build_card_from_dictation_intent
from engine.approval_tool_registry_with_vault_fallback import build_registry_for_vault_root
from engine.dictation.dictation_finalization import DictationFinalResult
from engine.dictation.dictation_intents_repository import get_dictation_intent
from engine.protocol import (
    EVENT_ENHANCE_FAILED,
    EVENT_ENHANCE_READY,
    Envelope,
    EnvelopeKind,
    EventBroadcastHub,
)
from engine.storage.extraction_results_repository import latest_extraction_row
from engine.storage.sqlite_connection import open_sqlite_connection
from engine.storage.sqlite_migrations_runner import apply_migrations
from engine.vault import VaultWriteError, resolve_vault_root

logger = logging.getLogger(__name__)


def _utc_now_iso() -> str:
    return datetime.now(tz=UTC).isoformat()


class ApprovalCardBuildWiring:
    """One per engine process; construction subscribes to the hub only."""

    def __init__(self, hub: EventBroadcastHub, db_path: Path, migrations_dir: Path) -> None:
        self._hub = hub
        self._db_path = db_path
        self._migrations_dir = migrations_dir
        self._unsubscribe = hub.subscribe(self._on_event)
        # Strong refs so a build task is never GC'd mid-flight.
        self._tasks: set[asyncio.Task[None]] = set()
        # Builds run one at a time: the builder's duplicate check is
        # check-then-insert, so concurrent passes over the same source row
        # could each see "no duplicate" (idempotency is per-pass, not racy).
        self._build_lock = asyncio.Lock()

    # -------------------------------------------------- finalization seam
    async def _on_event(self, envelope: Envelope) -> None:
        """Hub subscriber: cheap routing only; NEVER raises (see docstring)."""
        try:
            if envelope.kind is not EnvelopeKind.EVENT:
                return
            if envelope.name not in (EVENT_ENHANCE_READY, EVENT_ENHANCE_FAILED):
                return
            meeting_id = envelope.payload.get("meeting_id")
            if not isinstance(meeting_id, str) or not meeting_id:
                return  # type-guarded: malformed frames are skipped
            self._spawn(self._build_for_meeting(meeting_id))
        except Exception:
            logger.exception("approval-card build wiring failed handling %s", envelope.name)

    def _spawn(self, work: Coroutine[object, object, None]) -> None:
        """Off the broadcast path: the hub delivers events inline on the
        finalize call, so building runs as its own task."""
        task = asyncio.get_running_loop().create_task(work, name="approval-card-build")
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _build_for_meeting(self, meeting_id: str) -> None:
        """Latest extraction row of a FINALIZED meeting -> pending cards."""
        try:
            async with self._build_lock:
                await self._build_for_meeting_locked(meeting_id)
        except Exception:
            # Suggest-only: a failed build never costs the finalized note.
            logger.exception("building approval cards for meeting %s failed", meeting_id)

    async def _build_for_meeting_locked(self, meeting_id: str) -> None:
        await apply_migrations(self._db_path, self._migrations_dir)
        connection = await open_sqlite_connection(self._db_path)
        try:
            # AFTER-finalization-succeeds check, from the DB (fail closed:
            # a refused run also broadcasts enhance.failed — no cards).
            cursor = await connection.execute(
                "SELECT finalized_at FROM meetings WHERE id = ?", (meeting_id,)
            )
            row = await cursor.fetchone()
            await cursor.close()
            if row is None or row[0] is None:
                return
            latest = await latest_extraction_row(connection, meeting_id)
            if latest is None:
                return  # extraction unavailable for this run: nothing to suggest
            extraction_row_id, payload_json = latest
            built = await build_cards_from_extraction(
                connection,
                meeting_id=meeting_id,
                extraction_row_id=extraction_row_id,
                payload_json=payload_json,
                created_at=_utc_now_iso(),
            )
            await self._broadcast_created(connection, built.created_card_ids)
        finally:
            await connection.close()

    # ------------------------------------------------------ dictation seam
    async def on_dictation_final(self, result: DictationFinalResult) -> None:
        """Dictation gateway hook: one recorded intent -> at most one card.

        Runs inline (local SQL only) so the pending card's ``card.updated``
        precedes the dictation command's acknowledging reply.
        """
        if result.intent_row_id is None:
            return  # note/inject releases record no intent: nothing to build
        async with self._build_lock:  # same serialisation as meeting builds
            await apply_migrations(self._db_path, self._migrations_dir)
            connection = await open_sqlite_connection(self._db_path)
            try:
                record = await get_dictation_intent(connection, result.intent_row_id)
                if record is None:
                    return
                built = await build_card_from_dictation_intent(
                    connection, record=record, created_at=_utc_now_iso()
                )
                await self._broadcast_created(connection, built.created_card_ids)
            finally:
                await connection.close()

    # -------------------------------------------------------------- shared
    async def _broadcast_created(
        self, connection: aiosqlite.Connection, card_ids: tuple[int, ...]
    ) -> None:
        """One ``card.updated`` per newly created pending card."""
        if not card_ids:
            return
        try:
            vault_root: Path | None = resolve_vault_root()
        except VaultWriteError:
            vault_root = None  # previews degrade honestly, never crash
        registry = build_registry_for_vault_root(vault_root)
        for card_id in card_ids:
            record = await get_card(connection, card_id)
            if record is not None:
                await self._hub.broadcast_event(
                    CARD_UPDATED_EVENT_NAME, build_card_updated_payload(record, registry)
                )

    async def drain(self) -> None:
        """Await all in-flight build tasks (tests + orderly shutdown)."""
        tasks = [task for task in self._tasks if not task.done()]
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def shutdown(self) -> None:
        """Process shutdown: unsubscribe, finish quick builds, cancel rest."""
        self._unsubscribe()
        tasks = [task for task in self._tasks if not task.done()]
        if not tasks:
            return
        _, pending = await asyncio.wait(tasks, timeout=2.0)
        for task in pending:
            task.cancel()
            with contextlib.suppress(BaseException):
                await task
