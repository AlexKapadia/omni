"""``dictation.begin`` / ``dictation.end`` dispatch + session/finalizer wiring.

Purpose: the ADDITIVE M5 dictation surface, implemented EXACTLY per the
pinned spec in ``engine/dictation/dictation_protocol_names.py`` — begin
opens the mic-only STT session, end flushes it and runs the release
finalizer (note / command / inject), with ``dictation.partial`` /
``dictation.final`` / ``dictation.error`` events riding the broadcast hub.
This module lives in the SERVER layer so the dictation lane's own files
stay untouched (lane boundary); it composes only ``engine.dictation``'s
public names.
Pipeline position: called by the connection handler for any command whose
name is in ``DICTATION_COMMAND_NAMES``; sits above ``engine.dictation`` /
``engine.router`` / ``engine.index`` / ``engine.vault``.

Security invariants:
- A non-bool ``inject_requested`` is treated as False (deny by default — a
  malformed hint must never route text into a paste; pinned spec).
- Gateway construction is inert: models, keys, and the vault all resolve
  per session/call, so a missing dependency refuses THAT action honestly.
- ``dictation.error`` reasons are our own plain-voice messages (router
  errors already scrub key material at the client boundary).
"""

import logging
from collections.abc import Awaitable, Callable
from pathlib import Path

import aiosqlite

from engine.dictation.dictation_finalization import DictationFinalResult, DictationReleaseFinalizer
from engine.dictation.dictation_protocol_names import (
    DICTATION_BEGIN_COMMAND_NAME,
    DICTATION_END_COMMAND_NAME,
    DICTATION_ERROR_EVENT_NAME,
    DICTATION_FINAL_EVENT_NAME,
    DICTATION_PARTIAL_EVENT_NAME,
    build_dictation_error_payload,
    build_dictation_final_payload,
    build_dictation_partial_payload,
)
from engine.dictation.dictation_session_service import DictationSessionService
from engine.index import VaultIndexerService
from engine.protocol import PROTOCOL_VERSION, Envelope, EnvelopeKind, EventBroadcastHub
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

# The commands this dispatcher owns; the handler routes ONLY these here.
DICTATION_COMMAND_NAMES = frozenset({DICTATION_BEGIN_COMMAND_NAME, DICTATION_END_COMMAND_NAME})

# Additive error code (string literal beside the pinned enum, mirroring the
# meeting dispatcher's `finalize_error`).
DICTATION_ERROR_CODE = "dictation_error"

SendFn = Callable[[Envelope], Awaitable[None]]
# Injection seam: runs one release finalization (text, inject_requested,
# flush_ms) -> result. The DEFAULT owns the whole per-call I/O lifecycle
# (migrations, ledger connection, real finalizer); an injected fake does no
# I/O at all, keeping tests hermetic.
ReleaseFinalizeFn = Callable[[str, bool, int | None], Awaitable[DictationFinalResult]]


class DictationCommandGateway:
    """One per engine process; construction is inert (no keys, no I/O).

    The session service is engine-owned and long-lived (its models load on
    the first ``begin``); the release finalizer is built PER ``end`` call
    over that call's own connection, exactly like meeting finalization.
    """

    def __init__(
        self,
        hub: EventBroadcastHub,
        db_path: Path,
        migrations_dir: Path,
        session_service: DictationSessionService | None = None,
        release_finalize: ReleaseFinalizeFn | None = None,
    ) -> None:
        self._hub = hub
        self._db_path = db_path
        self._migrations_dir = migrations_dir
        # Live partials stream straight to every socket (the pill mirrors them).
        self._session = (
            session_service
            if session_service is not None
            else DictationSessionService(on_partial_text=self._broadcast_partial)
        )
        self._release_finalize = (
            release_finalize if release_finalize else self._default_release_finalize
        )

    async def _broadcast_partial(self, text: str) -> None:
        await self._hub.broadcast_event(
            DICTATION_PARTIAL_EVENT_NAME, build_dictation_partial_payload(text)
        )

    def _build_finalizer(self, connection: aiosqlite.Connection) -> DictationReleaseFinalizer:
        """Real finalizer per the pinned spec: real router, real intents
        connection factory, ``resolve_vault_root``, ``VaultIndexerService``.

        Only the REQUIRED seams are pinned here — the dictation lane is
        extending the finalizer additively, and its additive defaults must
        keep riding (do not pin them out; wiring-spec mandate).
        """

        async def record(entry: RouterLedgerEntry) -> None:
            # Append-only ledger row per external call (audit invariant).
            await insert_router_ledger_entry(connection, entry)

        router = ProviderRouter(build_provider_clients(ProviderKeyStore()), record)

        async def intents_connection() -> aiosqlite.Connection:
            # The finalizer closes what this factory opens (its contract).
            return await open_sqlite_connection(self._db_path)

        indexer: VaultIndexerService | None
        try:
            # Index over the same call-scoped connection; dense side stays
            # the documented BM25-only degradation (no embedder wired yet).
            indexer = VaultIndexerService(connection, resolve_vault_root())
        except VaultWriteError:
            # No configured vault: note mode will refuse honestly inside the
            # finalizer via resolve_vault_root; command/inject still work.
            indexer = None
        return DictationReleaseFinalizer(
            route=router.route,
            intents_connection_factory=intents_connection,
            vault_root_provider=resolve_vault_root,
            indexer=indexer,
        )

    async def _default_release_finalize(
        self, text: str, inject_requested: bool, flush_ms: int | None
    ) -> DictationFinalResult:
        """Per-call I/O lifecycle: schema, ledger connection, real finalizer."""
        await apply_migrations(self._db_path, self._migrations_dir)
        connection = await open_sqlite_connection(self._db_path)
        try:
            finalizer = self._build_finalizer(connection)
            return await finalizer.finalize(
                text, inject_requested=inject_requested, flush_ms=flush_ms
            )
        finally:
            await connection.close()

    async def begin(self) -> None:
        """Key down: open the mic session (raises loudly on failure)."""
        await self._session.begin()

    async def end(self, inject_requested: bool) -> DictationFinalResult:
        """Key up: flush STT, finalize the release, broadcast the outcome."""
        text = await self._session.end()
        result = await self._release_finalize(
            text,
            inject_requested,
            self._session.last_flush_ms,  # speed-showcase stamp (spec)
        )
        await self._hub.broadcast_event(
            DICTATION_FINAL_EVENT_NAME, build_dictation_final_payload(result)
        )
        return result

    async def broadcast_error(self, reason: str) -> None:
        """``dictation.error`` — the pill shows the plain-voice reason."""
        await self._hub.broadcast_event(
            DICTATION_ERROR_EVENT_NAME, build_dictation_error_payload(reason)
        )


async def dispatch_dictation_command(
    command: Envelope, gateway: DictationCommandGateway | None, send: SendFn
) -> None:
    """Handle one validated dictation.* command envelope, always replying."""
    if gateway is None:
        # Dictation not wired in this app instance: refuse honestly.
        await send(_dictation_error_reply(command.id, "dictation is not available"))
        return
    try:
        if command.name == DICTATION_BEGIN_COMMAND_NAME:
            # mode_hint is advisory UI state only — the engine's mode split
            # on release is authoritative; the service ignores it (spec).
            await gateway.begin()
        else:
            # Deny by default: ONLY the literal True may route text toward a
            # paste; any other value (missing, "yes", 1) is False (spec).
            inject = command.payload.get("inject_requested", False) is True
            await gateway.end(inject)
    except Exception as exc:
        logger.exception("%s failed", command.name)
        reason = str(exc) or exc.__class__.__name__
        await gateway.broadcast_error(reason)  # the pill's honest failure state
        await send(_dictation_error_reply(command.id, reason))
        return
    await send(
        Envelope(
            v=PROTOCOL_VERSION, kind=EnvelopeKind.REPLY, name="ok", id=command.id, payload={}
        )
    )


def _dictation_error_reply(reply_id: str, message: str) -> Envelope:
    return Envelope(
        v=PROTOCOL_VERSION,
        kind=EnvelopeKind.REPLY,
        name="error",
        id=reply_id,
        payload={"code": DICTATION_ERROR_CODE, "message": message},
    )
