"""Approval-card WS command/event surface — names + typed payload builders.

Purpose: the PINNED protocol-v1 additions for approval cards, documented
here so the orchestrator can wire them into ``engine/server.py`` /
``websocket_connection_handler.py`` at reconciliation WITHOUT this lane
touching M2's files. The UI mirrors these names in
``apps/ui/src/lib/approval-cards-store.ts``.

DEFERRED WIRING SPEC (orchestrator: implement exactly this):
- command ``cards.list`` {} -> reply {cards: [<card payload>, ...]} from
  ``approval_cards_repository.list_cards`` via
  :func:`build_card_payload` (newest first).
- command ``card.approve`` {id: int, edited_payload?: object} ->
  ``approval_cards_repository.approve_card(connection, id,
  decided_at=now_iso, edited_payload_json=json.dumps(edited_payload) if
  present)``. On success, schedule ``card_executor.execute_approved_card``
  (fire-and-forget task) and broadcast ``card.updated`` after EVERY status
  change (approved, executing, executed/failed). A False return (card was
  not pending) replies with an error payload — never a fake success.
- command ``card.dismiss`` {id: int} -> ``dismiss_card``; broadcast
  ``card.updated``.
- command ``card.retry`` {id: int} -> allowed ONLY on a 'failed' card:
  insert a NEW pending card cloned from the failed card's payload (0008
  makes failed terminal — history is never rewritten), then approve the
  clone with the same decided_at (the user's retry click IS the approval),
  execute, broadcast ``card.updated`` for the new card.
- event ``card.updated`` {card: <card payload>} on every status change.

Approval invariant note for the wiring: the ONLY call sites of
``execute_approved_card`` are the approve/retry handlers above and the
(future, default-EMPTY) instant-execute whitelist — nothing else may
execute a card.
"""

import json

from engine.agents.approval_card_types import ApprovalCardRecord
from engine.agents.card_to_tool_params_mapper import map_card_payload_to_tool_params
from engine.agents.tool_registry import ToolRegistry

# --- message names (pinned, dot-namespaced like "capture.start") ---
CARDS_LIST_COMMAND_NAME = "cards.list"
CARD_APPROVE_COMMAND_NAME = "card.approve"
CARD_DISMISS_COMMAND_NAME = "card.dismiss"
CARD_RETRY_COMMAND_NAME = "card.retry"
CARD_UPDATED_EVENT_NAME = "card.updated"


def build_card_payload(record: ApprovalCardRecord, registry: ToolRegistry) -> dict[str, object]:
    """One card as the UI sees it (pinned shape; the UI parses fail-closed).

    ``preview_lines`` are the tool's dry-run preview when the payload maps
    deterministically; otherwise honest generic field lines — the UI never
    invents a preview.
    """
    payload: dict[str, object] = {
        "id": record.id,
        "meeting_id": record.meeting_id,
        "source": record.source,
        "card_type": record.card_type,
        "status": record.status,
        "payload": _decoded_payload(record),
        "preview_lines": list(_preview_lines(record, registry)),
        "created_at": record.created_at,
        "decided_at": record.decided_at,
        "executed_at": record.executed_at,
        "error": record.error,
        "result_summary": _result_summary(record),
    }
    return payload


def build_card_updated_payload(
    record: ApprovalCardRecord, registry: ToolRegistry
) -> dict[str, object]:
    """{card}: the envelope payload for one ``card.updated`` event."""
    return {"card": build_card_payload(record, registry)}


def build_cards_list_reply_payload(
    records: list[ApprovalCardRecord], registry: ToolRegistry
) -> dict[str, object]:
    """{cards}: the reply payload for ``cards.list``."""
    return {"cards": [build_card_payload(record, registry) for record in records]}


def _decoded_payload(record: ApprovalCardRecord) -> dict[str, object]:
    """The stored payload as an object; {} when (impossibly) malformed."""
    try:
        decoded = json.loads(record.payload_json)
    except (json.JSONDecodeError, RecursionError):
        return {}
    return decoded if isinstance(decoded, dict) else {}


def _result_summary(record: ApprovalCardRecord) -> str | None:
    if record.result_json is None:
        return None
    try:
        decoded = json.loads(record.result_json)
    except (json.JSONDecodeError, RecursionError):
        return None
    summary = decoded.get("summary") if isinstance(decoded, dict) else None
    return summary if isinstance(summary, str) else None


def _preview_lines(record: ApprovalCardRecord, registry: ToolRegistry) -> tuple[str, ...]:
    """Dry-run preview when deterministic; honest field lines otherwise."""
    from engine.agents.agents_errors import AgentsError  # local: avoid cycle

    try:
        from engine.agents.approval_card_types import parse_card_payload

        payload = parse_card_payload(record.card_type, record.payload_json)
        outcome = map_card_payload_to_tool_params(payload)
        if outcome.params is not None:
            return registry.tool_for_card_type(record.card_type).dry_run(outcome.params)
    except AgentsError:
        pass  # fall through to generic lines — never a crashed preview
    decoded = _decoded_payload(record)
    lines = tuple(
        f"{key}: {value}"
        for key, value in decoded.items()
        if isinstance(value, (str, int, float)) and str(value).strip()
    )
    return lines or ("Details pending",)
