"""M4 agents layer: approval cards, the tool registry, and the executor.

Where it sits: reads the append-only source rows (extraction_results 0005,
dictation_intents 0007), stores typed cards in ``approval_cards`` (0008 —
the status machine lives in the SCHEMA), and executes ONLY schema-approved
cards through the five registered tools (calendar event, free slot,
contact upsert, vault note, Gmail DRAFT).

Binding invariants carried by this package (claude.md §5.6):
- Approval-before-execute: no tool runs without an approved card; the
  executor's transactional claim is the TOCTOU defence.
- Draft-only Gmail: no send capability exists anywhere in this package.
- Every executed action appends exactly one immutable audit_log row.
"""

from engine.agents.approval_card_builder import (
    DICTATION_CONFIDENCE_FLOOR,
    BuiltCards,
    build_cards_from_extraction,
)
from engine.agents.approval_card_types import (
    ApprovalCardRecord,
    CardStatus,
    CardType,
    parse_card_payload,
)
from engine.agents.approval_protocol_names import (
    CARD_APPROVE_COMMAND_NAME,
    CARD_DISMISS_COMMAND_NAME,
    CARD_RETRY_COMMAND_NAME,
    CARD_UPDATED_EVENT_NAME,
    CARDS_LIST_COMMAND_NAME,
    build_card_payload,
    build_card_updated_payload,
    build_cards_list_reply_payload,
)
from engine.agents.card_executor import CardExecutionReport, execute_approved_card
from engine.agents.default_tool_registry import build_default_tool_registry
from engine.agents.dictation_intent_card_builder import build_card_from_dictation_intent
from engine.agents.tool_registry import AgentTool, ToolRegistry, ToolResult

__all__ = [
    "CARDS_LIST_COMMAND_NAME",
    "CARD_APPROVE_COMMAND_NAME",
    "CARD_DISMISS_COMMAND_NAME",
    "CARD_RETRY_COMMAND_NAME",
    "CARD_UPDATED_EVENT_NAME",
    "DICTATION_CONFIDENCE_FLOOR",
    "AgentTool",
    "ApprovalCardRecord",
    "BuiltCards",
    "CardExecutionReport",
    "CardStatus",
    "CardType",
    "ToolRegistry",
    "ToolResult",
    "build_card_from_dictation_intent",
    "build_card_payload",
    "build_card_updated_payload",
    "build_cards_from_extraction",
    "build_cards_list_reply_payload",
    "build_default_tool_registry",
    "execute_approved_card",
    "parse_card_payload",
]
