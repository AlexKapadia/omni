"""``ask.query`` dispatch for the WS handler + the per-query service gateway.

Purpose: the ADDITIVE M3 chat surface — validates the untrusted question,
builds one :class:`AskOmniAnswerService` over a fresh database connection,
BM25 retrieval (the dense side stays an explicit BM25-only degradation
until the vec model ships), and the real keyed router, then answers with
the pinned ``ask.answer`` reply. Keeps the diff inside
``engine.websocket_connection_handler`` to a single delegation branch
(same pattern as the meeting/naomi dispatchers).
Pipeline position: called by the connection handler for any command whose
name is in ``ASK_COMMAND_NAMES``; sits above ``engine.ask`` /
``engine.index`` / ``engine.router``.

Security invariants:
- The query is strictly validated (deny by default) and travels only as
  untrusted DATA through the ask service's message channel.
- Gateway construction is inert (no keys, no I/O): providers resolve per
  query, so a missing key refuses that query, never engine boot.
- Router refusals (kill switch, chain exhausted) become structured
  ``error`` replies — never a fabricated answer (fail honest).
"""

import logging
from collections.abc import Awaitable, Callable
from pathlib import Path

from pydantic import ValidationError

# Pinned names come from the package's own contract (no drift); importing
# the package __init__ is cycle-safe because it never imports this module.
from engine.ask import ASK_ANSWER_REPLY_NAME, ASK_QUERY_COMMAND_NAME
from engine.ask.ask_answer_contracts import AskAnswer, ask_answer_to_payload
from engine.ask.ask_omni_answer_service import AskOmniAnswerService
from engine.index import HybridRrfRetriever
from engine.protocol import (
    PROTOCOL_VERSION,
    AskQueryCommandPayload,
    Envelope,
    EnvelopeKind,
    ProtocolErrorCode,
    error_reply,
)
from engine.router import (
    ProviderRouter,
    RouterError,
    RouterLedgerEntry,
    build_provider_clients,
    insert_router_ledger_entry,
)
from engine.security import ProviderKeyStore
from engine.storage.sqlite_connection import open_sqlite_connection
from engine.storage.sqlite_migrations_runner import apply_migrations

logger = logging.getLogger(__name__)

# The commands this dispatcher owns; the handler routes ONLY these here.
ASK_COMMAND_NAMES = frozenset({ASK_QUERY_COMMAND_NAME})

# Additive error code (string literal beside the pinned enum, mirroring the
# meeting dispatcher's `finalize_error`).
ASK_ERROR_CODE = "ask_error"

SendFn = Callable[[Envelope], Awaitable[None]]
# Same seam shape as the finalization service's RouterFactory: the recorder
# binds the append-only ledger to the query's own connection.
LedgerRecorder = Callable[[RouterLedgerEntry], Awaitable[None]]
AskRouterFactory = Callable[[LedgerRecorder], ProviderRouter]


def _default_ask_router_factory(recorder: LedgerRecorder) -> ProviderRouter:
    """Real router: keyed clients only, ledger-bound (built per query)."""
    clients = build_provider_clients(ProviderKeyStore())
    return ProviderRouter(clients, recorder)


class AskAnswerGateway:
    """One per engine process; construction is inert (no keys, no I/O).

    Each query opens its own connection (schema ensured first), builds the
    retriever and router over it, answers, and closes — the same
    per-request lifecycle as meeting finalization.
    """

    def __init__(
        self,
        db_path: Path,
        migrations_dir: Path,
        router_factory: AskRouterFactory | None = None,
    ) -> None:
        self.db_path = db_path
        self.migrations_dir = migrations_dir
        self._router_factory = router_factory if router_factory else _default_ask_router_factory

    async def answer(self, query: str) -> AskAnswer:
        """Run the full ask pipeline for one question (see class docstring)."""
        await apply_migrations(self.db_path, self.migrations_dir)
        connection = await open_sqlite_connection(self.db_path)
        try:
            # Dense side EXPLICITLY absent: BM25-only until the vec model
            # ships (documented degradation, never a silent one — see
            # HybridRrfRetriever's contract and the m3-index ledger row).
            retriever = HybridRrfRetriever(connection, None, None)

            async def record(entry: RouterLedgerEntry) -> None:
                # Append-only ledger row per external call (audit invariant).
                await insert_router_ledger_entry(connection, entry)

            router = self._router_factory(record)
            service = AskOmniAnswerService(connection, retriever, router)
            return await service.answer(query)
        finally:
            await connection.close()


async def dispatch_ask_command(
    command: Envelope, gateway: AskAnswerGateway | None, send: SendFn
) -> None:
    """Handle one validated ask.* command envelope, always replying."""
    try:
        payload = AskQueryCommandPayload.model_validate(command.payload)
    except ValidationError:
        await send(
            error_reply(
                command.id, ProtocolErrorCode.INVALID_PAYLOAD, "ask.query payload failed validation"
            )
        )
        return
    if gateway is None:
        # Ask not wired in this app instance: refuse honestly.
        await send(_ask_error_reply(command.id, "ask is not available"))
        return
    try:
        answer = await gateway.answer(payload.query)
    except RouterError as exc:
        # Fail honest: kill switch / exhausted chain surfaces as a typed
        # refusal in the UI's error state, never as a fabricated answer.
        await send(_ask_error_reply(command.id, str(exc)))
        return
    except Exception as exc:
        logger.exception("ask.query failed")
        await send(_ask_error_reply(command.id, f"ask failed: {exc}"))
        return
    await send(
        Envelope(
            v=PROTOCOL_VERSION,
            kind=EnvelopeKind.REPLY,
            name=ASK_ANSWER_REPLY_NAME,  # pinned reply name (UI correlates by id)
            id=command.id,
            payload=ask_answer_to_payload(answer),
        )
    )


def _ask_error_reply(reply_id: str, message: str) -> Envelope:
    return Envelope(
        v=PROTOCOL_VERSION,
        kind=EnvelopeKind.REPLY,
        name="error",
        id=reply_id,
        payload={"code": ASK_ERROR_CODE, "message": message},
    )
