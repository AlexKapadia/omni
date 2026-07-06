"""Approval-cards gateway: list, decide, and execute cards for the WS surface.

Purpose: the server-layer object behind the ``cards.list`` / ``card.*``
commands, implementing EXACTLY the pinned spec in
``engine/agents/approval_protocol_names.py`` — per-command connection
lifecycle, the ONLY approve/retry call sites of ``execute_approved_card``,
and a ``card.updated`` broadcast after EVERY status change (pending clone,
approved, executing, executed/failed, dismissed).
Pipeline position: constructed by ``engine.server``'s app factory (inert —
no keys, no I/O); driven by ``engine.approval_command_dispatcher``.

Security invariants:
- Approval-before-execute: execution is scheduled ONLY from approve/retry,
  and the executor's transactional claim re-proves the 'approved' state.
- Fail closed on Google (the DPAPI session refuses when not connected) and
  on the vault (``approval_tool_registry_with_vault_fallback``).
- Pre-approval edits are validated against the card's typed payload model
  before the approve statement (what-you-approved-is-what-executes).
"""

import asyncio
import contextlib
import json
import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from pathlib import Path

from engine.agents.agents_errors import CardNotExecutableError, CardPayloadInvalidError
from engine.agents.approval_card_types import ApprovalCardRecord, parse_card_payload
from engine.agents.approval_cards_repository import (
    approve_card,
    dismiss_card,
    get_card,
    insert_pending_card,
    list_cards,
)
from engine.agents.approval_protocol_names import (
    CARD_UPDATED_EVENT_NAME,
    build_card_updated_payload,
    build_cards_list_reply_payload,
)
from engine.agents.card_executor import execute_approved_card
from engine.agents.tool_registry import ToolRegistry
from engine.approval_tool_registry_with_vault_fallback import build_registry_for_vault_root
from engine.google.google_session import DpapiGoogleSession, GoogleSession
from engine.protocol import EventBroadcastHub
from engine.router import (
    ProviderRouter,
    RouterLedgerEntry,
    build_provider_clients,
    insert_router_ledger_entry,
)
from engine.security import ProviderKeyStore
from engine.storage.sqlite_connection import open_sqlite_connection
from engine.storage.sqlite_migrations_runner import apply_migrations
from engine.vault import VaultWriteError, resolve_vault_root

logger = logging.getLogger(__name__)

# Seams (typed) so tests inject fakes and production wires the real deps.
RegistryFactory = Callable[[Path | None], ToolRegistry]
GoogleSessionFactory = Callable[[], GoogleSession]
LedgerRecorder = Callable[[RouterLedgerEntry], Awaitable[None]]
RouterFactory = Callable[[LedgerRecorder], ProviderRouter]
VaultRootResolver = Callable[[], Path]


class CardCommandRefused(Exception):
    """Honest refusal (unknown id / illegal transition / invalid edit) —
    the dispatcher turns it into a typed ``card_error`` reply."""


def _utc_now_iso() -> str:
    return datetime.now(tz=UTC).isoformat()


def _default_router_factory(recorder: LedgerRecorder) -> ProviderRouter:
    """Real router (LLM param-mapping fallback): keyed clients, ledger-bound."""
    return ProviderRouter(build_provider_clients(ProviderKeyStore()), recorder)


class ApprovalCardsGateway:
    """One per engine process; construction is inert (no keys, no I/O).

    Every command opens its own connection (schema ensured first), works,
    and closes — the same per-request lifecycle as the ask gateway.
    Execution runs as a background task over its OWN connection so the
    socket reply never waits on a tool.
    """

    def __init__(
        self,
        hub: EventBroadcastHub,
        db_path: Path,
        migrations_dir: Path,
        registry_factory: RegistryFactory | None = None,
        google_session_factory: GoogleSessionFactory | None = None,
        router_factory: RouterFactory | None = None,
        vault_root_resolver: VaultRootResolver | None = None,
        now_iso: Callable[[], str] = _utc_now_iso,
    ) -> None:
        self._hub = hub
        self._db_path = db_path
        self._migrations_dir = migrations_dir
        self._registry_factory = registry_factory or build_registry_for_vault_root
        # Fail closed by default: no DPAPI tokens -> "Google account not
        # connected" raised inside the executor, recorded on the card.
        self._google_session_factory = google_session_factory or DpapiGoogleSession
        self._router_factory = router_factory or _default_router_factory
        self._vault_root_resolver = vault_root_resolver or resolve_vault_root
        self._now_iso = now_iso
        # Strong refs: a GC'd task would silently drop a running execution.
        self._execution_tasks: set[asyncio.Task[None]] = set()

    # ------------------------------------------------------------- plumbing
    def _resolve_vault_root(self) -> Path | None:
        try:
            return self._vault_root_resolver()
        except VaultWriteError:
            return None  # unconfigured vault: preview-only registry below

    def _registry(self) -> ToolRegistry:
        return self._registry_factory(self._resolve_vault_root())

    async def _broadcast_card(self, record: ApprovalCardRecord, registry: ToolRegistry) -> None:
        """card.updated {card} — the pinned event, after every status change."""
        await self._hub.broadcast_event(
            CARD_UPDATED_EVENT_NAME, build_card_updated_payload(record, registry)
        )

    # ------------------------------------------------------------- commands
    async def list_cards_payload(self) -> dict[str, object]:
        """cards.list -> {cards: [...]} newest first (pinned reply shape)."""
        await apply_migrations(self._db_path, self._migrations_dir)
        connection = await open_sqlite_connection(self._db_path)
        try:
            records = await list_cards(connection)
        finally:
            await connection.close()
        return build_cards_list_reply_payload(records, self._registry())

    async def approve(self, card_id: int, edited_payload: dict[str, object] | None) -> None:
        """pending -> approved (+ optional pre-approval edit), then execute."""
        await apply_migrations(self._db_path, self._migrations_dir)
        connection = await open_sqlite_connection(self._db_path)
        try:
            record = await get_card(connection, card_id)
            if record is None:
                raise CardCommandRefused(f"card {card_id} does not exist")
            edited_json: str | None = None
            if edited_payload is not None:
                if record.status != "pending":
                    # 0008 locks payload_json after the decision; refuse
                    # before SQL so the reason is plain, not a trigger abort.
                    raise CardCommandRefused(
                        f"edited_payload is only valid on a pending card — "
                        f"card {card_id} is '{record.status}'"
                    )
                edited_json = json.dumps(edited_payload, ensure_ascii=False)
                try:
                    # what-you-approved-is-what-executes: an edit that cannot
                    # validate must never become the frozen approved payload.
                    parse_card_payload(record.card_type, edited_json)
                except CardPayloadInvalidError as error:
                    raise CardCommandRefused(str(error)) from error
            changed = await approve_card(
                connection, card_id, decided_at=self._now_iso(), edited_payload_json=edited_json
            )
            if not changed:
                current = await get_card(connection, card_id)
                described = "missing" if current is None else f"'{current.status}'"
                raise CardCommandRefused(
                    f"card {card_id} is {described}, not 'pending' — approval refused"
                )
            approved = await get_card(connection, card_id)
        finally:
            await connection.close()
        if approved is not None:
            await self._broadcast_card(approved, self._registry())
        self._schedule_execution(card_id)

    async def dismiss(self, card_id: int) -> None:
        """pending -> dismissed; a non-pending card refuses honestly."""
        await apply_migrations(self._db_path, self._migrations_dir)
        connection = await open_sqlite_connection(self._db_path)
        try:
            changed = await dismiss_card(connection, card_id, decided_at=self._now_iso())
            if not changed:
                current = await get_card(connection, card_id)
                described = "missing" if current is None else f"'{current.status}'"
                raise CardCommandRefused(
                    f"card {card_id} is {described}, not 'pending' — dismissal refused"
                )
            dismissed = await get_card(connection, card_id)
        finally:
            await connection.close()
        if dismissed is not None:
            await self._broadcast_card(dismissed, self._registry())

    async def retry(self, card_id: int) -> None:
        """failed card -> NEW pending clone, approved and executed.

        0008 makes 'failed' terminal — history is never rewritten; the
        user's retry click IS the approval of the clone (pinned spec).
        """
        await apply_migrations(self._db_path, self._migrations_dir)
        connection = await open_sqlite_connection(self._db_path)
        try:
            failed = await get_card(connection, card_id)
            if failed is None:
                raise CardCommandRefused(f"card {card_id} does not exist")
            if failed.status != "failed":
                raise CardCommandRefused(
                    f"retry is only valid on a failed card — card {card_id} "
                    f"is '{failed.status}'"
                )
            now = self._now_iso()
            new_id = await insert_pending_card(
                connection,
                meeting_id=failed.meeting_id,
                source=failed.source,
                source_row_id=failed.source_row_id,
                card_type=failed.card_type,
                payload_json=failed.payload_json,  # the exact payload the user saw
                created_at=now,
            )
            pending = await get_card(connection, new_id)
            await approve_card(connection, new_id, decided_at=now)
            approved = await get_card(connection, new_id)
        finally:
            await connection.close()
        registry = self._registry()
        if pending is not None:
            await self._broadcast_card(pending, registry)  # the clone appears
        if approved is not None:
            await self._broadcast_card(approved, registry)
        self._schedule_execution(new_id)

    # ------------------------------------------------------------ execution
    def _schedule_execution(self, card_id: int) -> None:
        """Fire-and-forget execution task (pinned spec) with a strong ref."""
        task = asyncio.get_running_loop().create_task(
            self._execute_card(card_id), name=f"approval-card-execute-{card_id}"
        )
        self._execution_tasks.add(task)
        task.add_done_callback(self._execution_tasks.discard)

    async def _execute_card(self, card_id: int) -> None:
        """Run one approved card; broadcast executing then executed/failed."""
        try:
            registry = self._registry()
            vault_root = self._resolve_vault_root()
            connection = await open_sqlite_connection(self._db_path)
            try:

                async def record_ledger(entry: RouterLedgerEntry) -> None:
                    # Append-only ledger row per external call (audit invariant).
                    await insert_router_ledger_entry(connection, entry)

                async def on_claimed(record: ApprovalCardRecord) -> None:
                    # The DB row IS 'executing' here — broadcast the truth.
                    await self._broadcast_card(record, registry)

                await execute_approved_card(
                    connection,
                    card_id,
                    registry=registry,
                    google_session=self._google_session_factory(),
                    vault_root=vault_root,
                    router=self._router_factory(record_ledger),
                    on_claimed=on_claimed,
                )
                final = await get_card(connection, card_id)
            finally:
                await connection.close()
            if final is not None:
                await self._broadcast_card(final, registry)  # executed/failed
        except CardNotExecutableError as error:
            # Lost a race or the state moved: exactly-once means do nothing.
            logger.warning("approval card execution refused: %s", error)
        except Exception:
            # A wiring failure must never take the event loop down.
            logger.exception("approval card %s execution wiring failed", card_id)

    async def shutdown(self) -> None:
        """Let in-flight executions finish briefly, then cancel stragglers.

        Grace first: a cancelled claim strands a card in 'executing' (only
        'failed' is retryable), so honesty favours letting the executor
        record its real outcome when it can.
        """
        tasks = [task for task in self._execution_tasks if not task.done()]
        if not tasks:
            return
        _, pending = await asyncio.wait(tasks, timeout=5.0)
        for task in pending:
            task.cancel()
            with contextlib.suppress(BaseException):
                await task
