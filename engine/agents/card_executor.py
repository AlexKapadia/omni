"""The card executor — the ONLY path from an approved card to a real action.

Purpose: take one ``approval_cards`` row, prove it is genuinely 'approved'
(transactional claim — TOCTOU defence), translate its payload into concrete
tool parameters (DETERMINISTIC MAPPING FIRST; router function-calling only
for genuinely ambiguous fields, because symbolic code cannot resolve
"lunch with Tom Friday at 1" without inventing meaning), execute the tool,
and leave a complete trail: result on the card, EXACTLY ONE append-only
audit row, a daily-note line, and an Actions-region line on the meeting
note when there is one.
Pipeline position: called by the (deferred) server wiring when a card
reaches 'approved'; sits on the repository, mapper, registry, and vault.

Security invariants (claude.md §5.6 project bindings):
- APPROVAL-BEFORE-EXECUTE: the claim re-reads the row and flips
  approved->executing inside one immediate transaction; a card in any
  other state — or claimed by a racing executor — is refused, typed.
- EVERY execution attempt (success AND failure) writes exactly one
  audit_log row: what ran, when, which provider (if any), and what data
  left the machine. An action the audit insert cannot record does not get
  reported as success.
- Kill switch: NOT checked here globally — local vault tools must keep
  working with it engaged (fail closed on egress, never on the user's own
  data). The Google gateway and the router each refuse egress themselves.
"""

import json
import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import aiosqlite
from pydantic import ValidationError

from engine.agents.agents_errors import AgentsError, CardNotExecutableError
from engine.agents.approval_card_types import ApprovalCardRecord, parse_card_payload
from engine.agents.approval_cards_repository import (
    claim_card_for_execution,
    finish_card_executed,
    finish_card_failed,
    get_card,
)
from engine.agents.card_to_tool_params_mapper import map_card_payload_to_tool_params
from engine.agents.executed_action_vault_trace import write_executed_action_vault_trace
from engine.agents.llm_function_call_mapper import map_via_router_function_call
from engine.agents.tool_registry import ToolRegistry, ToolResult
from engine.google.google_auth_errors import GoogleError
from engine.google.google_session import GoogleSession
from engine.router.fallback_executor import ProviderRouter
from engine.router.router_errors import RouterError
from engine.vault.vault_errors import VaultWriteError

_logger = logging.getLogger(__name__)

AUDIT_ACTION_EXECUTED = "agent.card_executed"
AUDIT_ACTION_FAILED = "agent.card_execution_failed"



def _utc_now_iso() -> str:
    return datetime.now(tz=UTC).isoformat()


@dataclass(frozen=True)
class CardExecutionReport:
    """What one execution attempt did — the compact, honest account."""

    card_id: int
    final_status: str  # "executed" | "failed"
    summary_line: str | None
    error: str | None
    mapping: str | None  # "deterministic" | "llm" | None (failed before mapping)
    provider: str | None  # LLM-mapping provider, when one was used
    vault_trace_error: str | None  # honest partial: action ran, trace failed


async def execute_approved_card(
    connection: aiosqlite.Connection,
    card_id: int,
    *,
    registry: ToolRegistry,
    google_session: GoogleSession,
    vault_root: Path | None,
    router: ProviderRouter | None = None,
    now_iso: Callable[[], str] = _utc_now_iso,
) -> CardExecutionReport:
    """Execute one approved card end-to-end. See module docstring.

    Raises :class:`CardNotExecutableError` when the card is not claimable
    (never approved, already decided, or lost the race). Every claimed card
    finishes as 'executed' or 'failed' with exactly one audit row.
    """
    record = await claim_card_for_execution(connection, card_id)
    if record is None:
        existing = await get_card(connection, card_id)
        # fail-closed + exactly-once: whoever did not claim it does nothing.
        raise CardNotExecutableError(card_id, None if existing is None else existing.status)

    mapping: str | None = None
    provider: str | None = None
    try:
        payload = parse_card_payload(record.card_type, record.payload_json)
        tool = registry.tool_for_card_type(record.card_type)
        outcome = map_card_payload_to_tool_params(payload)
        if outcome.params is not None:
            mapping = "deterministic"
            params = outcome.params
        else:
            mapping = "llm"
            params, provider = await map_via_router_function_call(
                router, tool, record, outcome.ambiguity_reason or "ambiguous fields"
            )
        result = await tool.execute(params, google_session)
    except (AgentsError, GoogleError, RouterError, VaultWriteError, ValidationError) as error:
        return await _finish_failed(connection, record, str(error), mapping, provider, now_iso)
    except OSError as error:  # disk/network-adjacent surprises stay honest
        return await _finish_failed(
            connection, record, f"{type(error).__name__}: {error}", mapping, provider, now_iso
        )

    vault_trace_error = await write_executed_action_vault_trace(
        connection, record, result, vault_root
    )
    if vault_trace_error is not None:
        # The action DID run; the trace failure is reported, never hidden.
        result.detail["vault_trace_error"] = vault_trace_error

    ts = now_iso()
    # Audit BEFORE the status flip: an executed action that cannot be
    # audited must not be presented as a clean success (every-action-logged
    # invariant); the insert error propagates and the card stays 'executing'.
    await _insert_audit_row(
        connection, AUDIT_ACTION_EXECUTED, record, mapping, provider, result, error=None, ts=ts
    )
    result_json = json.dumps(
        {"summary": result.summary_line, "detail": result.detail}, ensure_ascii=False
    )
    await finish_card_executed(connection, record.id, executed_at=ts, result_json=result_json)
    return CardExecutionReport(
        card_id=record.id,
        final_status="executed",
        summary_line=result.summary_line,
        error=None,
        mapping=mapping,
        provider=provider,
        vault_trace_error=vault_trace_error,
    )


async def _finish_failed(
    connection: aiosqlite.Connection,
    record: ApprovalCardRecord,
    error_message: str,
    mapping: str | None,
    provider: str | None,
    now_iso: Callable[[], str],
) -> CardExecutionReport:
    """Record a failed attempt: one audit row + executing->failed."""
    ts = now_iso()
    await _insert_audit_row(
        connection,
        AUDIT_ACTION_FAILED,
        record,
        mapping,
        provider,
        result=None,
        error=error_message,
        ts=ts,
    )
    await finish_card_failed(connection, record.id, executed_at=ts, error=error_message)
    return CardExecutionReport(
        card_id=record.id,
        final_status="failed",
        summary_line=None,
        error=error_message,
        mapping=mapping,
        provider=provider,
        vault_trace_error=None,
    )


async def _insert_audit_row(
    connection: aiosqlite.Connection,
    action: str,
    record: ApprovalCardRecord,
    mapping: str | None,
    provider: str | None,
    result: ToolResult | None,
    *,
    error: str | None,
    ts: str,
) -> None:
    """EXACTLY ONE append-only audit row per execution attempt (§5.6)."""
    payload = {
        "card_id": record.id,
        "card_type": record.card_type,
        "source": record.source,
        "source_row_id": record.source_row_id,
        "meeting_id": record.meeting_id,
        "mapping": mapping,
        "provider": provider,  # which provider, when LLM mapping ran
        # what data left the machine — "" means the action was local-only
        "data_sent_off_machine": "" if result is None else result.data_sent_off_machine,
    }
    result_json = json.dumps(
        {"summary": result.summary_line} if result is not None else {"error": error},
        ensure_ascii=False,
    )
    await connection.execute(
        "INSERT INTO audit_log (ts, action, payload_json, result_json) VALUES (?, ?, ?, ?)",
        (ts, action, json.dumps(payload, ensure_ascii=False), result_json),
    )
