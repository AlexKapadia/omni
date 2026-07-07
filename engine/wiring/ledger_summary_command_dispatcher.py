"""``ledger.summary`` gateway + WS dispatch: the real router cost/latency view.

Purpose: the server-layer surface behind the Settings screen's cost/latency
ledger (speed is a showcase feature). Reads REAL ``router_ledger`` rows and
returns per-provider + per-task aggregates, a recent-calls feed, and grand
totals — every cost an EXACT decimal STRING.
Pipeline position: driven by the connection handler for ``ledger.summary``;
speaks only ``engine.protocol`` shapes; reads
``engine.router.router_ledger_repository``.

Correctness / security invariants:
- Costs are summed engine-side in ``Decimal`` and serialised as STRINGS —
  float arithmetic never touches the money path (claude.md §3.11); the UI
  renders the strings verbatim.
- Read-only: this surface only SELECTs (the ledger is append-only).
- Strict payload validation (extra fields forbidden) — deny by default.
"""

import logging
from collections.abc import Awaitable, Callable
from decimal import Decimal
from pathlib import Path

from pydantic import ValidationError

from engine.protocol import (
    COMMAND_LEDGER_SUMMARY,
    PROTOCOL_VERSION,
    Envelope,
    EnvelopeKind,
    LedgerSummaryCommandPayload,
    ProtocolErrorCode,
    error_reply,
)
from engine.router.router_ledger_repository import (
    ProviderLedgerSummary,
    RouterLedgerEntry,
    TaskLedgerSummary,
    recent_router_ledger_entries,
    summarize_router_ledger_by_provider,
    summarize_router_ledger_by_task,
)
from engine.storage.sqlite_connection import open_sqlite_connection
from engine.storage.sqlite_migrations_runner import apply_migrations

logger = logging.getLogger(__name__)

LEDGER_COMMAND_NAMES = frozenset({COMMAND_LEDGER_SUMMARY})

LEDGER_ERROR_CODE = "ledger_error"

SendFn = Callable[[Envelope], Awaitable[None]]


def _ok_reply(reply_id: str, payload: dict[str, object]) -> Envelope:
    return Envelope(
        v=PROTOCOL_VERSION, kind=EnvelopeKind.REPLY, name="ok", id=reply_id, payload=payload
    )


def _provider_row(row: ProviderLedgerSummary) -> dict[str, object]:
    return {
        "provider": row.provider,
        "total_calls": row.total_calls,
        "ok_calls": row.ok_calls,
        "error_calls": row.error_calls,
        "prompt_tokens": row.prompt_tokens,
        "completion_tokens": row.completion_tokens,
        # Exact string, never a float — the UI prints this verbatim.
        "total_cost_usd": str(row.total_cost_usd),
        "avg_latency_ms": row.avg_latency_ms,
    }


def _task_row(row: TaskLedgerSummary) -> dict[str, object]:
    return {
        "task": row.task_type,
        "total_calls": row.total_calls,
        "prompt_tokens": row.prompt_tokens,
        "completion_tokens": row.completion_tokens,
        "total_cost_usd": str(row.total_cost_usd),
        "avg_latency_ms": row.avg_latency_ms,
    }


def _recent_row(entry: RouterLedgerEntry) -> dict[str, object]:
    return {
        "ts": entry.ts,
        "task_type": entry.task_type,
        "provider": entry.provider,
        "model": entry.model,
        "latency_ms": entry.latency_ms,
        "prompt_tokens": entry.prompt_tokens,
        "completion_tokens": entry.completion_tokens,
        "est_cost_usd": str(entry.est_cost_usd),
        "outcome": entry.outcome,
        "error_class": entry.error_class,
    }


class LedgerSummaryCommandGateway:
    """One per engine process; construction is inert (no I/O until a command)."""

    def __init__(self, db_path: Path, migrations_dir: Path) -> None:
        self._db_path = db_path
        self._migrations_dir = migrations_dir

    async def summary_payload(self, limit: int) -> dict[str, object]:
        """Read the ledger and shape the honest summary (costs as strings)."""
        await apply_migrations(self._db_path, self._migrations_dir)
        connection = await open_sqlite_connection(self._db_path)
        try:
            by_provider = await summarize_router_ledger_by_provider(connection)
            by_task = await summarize_router_ledger_by_task(connection)
            recent = await recent_router_ledger_entries(connection, limit)
        finally:
            await connection.close()
        # Grand totals summed in Decimal from the same exact rows.
        total_calls = sum(row.total_calls for row in by_provider)
        prompt_tokens = sum(row.prompt_tokens for row in by_provider)
        completion_tokens = sum(row.completion_tokens for row in by_provider)
        total_cost = sum((row.total_cost_usd for row in by_provider), Decimal(0))
        return {
            "by_provider": [_provider_row(row) for row in by_provider],
            "by_task": [_task_row(row) for row in by_task],
            "totals": {
                "total_calls": total_calls,
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_cost_usd": str(total_cost),
            },
            "recent": [_recent_row(entry) for entry in recent],
        }


async def dispatch_ledger_command(
    command: Envelope, gateway: LedgerSummaryCommandGateway | None, send: SendFn
) -> None:
    """Handle one validated ledger.summary command, always replying (fail closed)."""
    if gateway is None:
        await send(
            error_reply(
                command.id, ProtocolErrorCode.UNKNOWN_COMMAND, "the ledger is not available"
            )
        )
        return
    try:
        payload = LedgerSummaryCommandPayload.model_validate(command.payload)
    except ValidationError:
        await send(
            error_reply(
                command.id,
                ProtocolErrorCode.INVALID_PAYLOAD,
                "ledger.summary payload failed validation",
            )
        )
        return
    try:
        result = await gateway.summary_payload(payload.limit)
    except Exception:
        logger.exception("ledger.summary failed")
        await send(
            Envelope(
                v=PROTOCOL_VERSION,
                kind=EnvelopeKind.REPLY,
                name="error",
                id=command.id,
                payload={"code": LEDGER_ERROR_CODE, "message": "the ledger could not be read"},
            )
        )
        return
    await send(_ok_reply(command.id, result))
