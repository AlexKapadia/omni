"""The agent tool registry — the COMPLETE capability surface of M4.

Purpose: one explicit mapping from card type to the single tool that can
execute it. If a capability is not in this registry, the engine cannot do
it — deny by default. The executor resolves tools ONLY through here.
Pipeline position: built once by the (deferred) server wiring via
:func:`build_default_tool_registry`; consumed by ``card_executor``.

Security invariants (binding):
- DRAFT-ONLY: there is NO send tool. The Gmail capability is exactly
  ``gmail_create_draft_tool`` — the registry cannot express dispatching
  mail because no such tool exists anywhere in the codebase. Tests scan
  these sources to keep it that way.
- Approval-before-execute: tools are reachable exclusively through the
  executor, which only runs cards the 0008 schema let reach 'approved'.
- One tool per card type; duplicates are refused at construction.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field

from pydantic import BaseModel

from engine.agents.agents_errors import UnknownCardTypeError
from engine.agents.approval_card_types import CardType
from engine.google.google_session import GoogleSession


@dataclass(frozen=True)
class ToolResult:
    """What one executed tool reports back (feeds result_json + audit).

    ``data_sent_off_machine`` is the honest, human-readable statement of
    exactly what left the box (empty string for local-only tools) — it goes
    verbatim into the append-only audit log (§5.6 minimum-data account).
    """

    summary_line: str
    detail: dict[str, object] = field(default_factory=dict)
    data_sent_off_machine: str = ""


class AgentTool:
    """Interface every tool implements (plain base class so isinstance
    works and fakes are trivial in tests).

    ``dry_run`` renders the card-UI preview lines from validated params —
    pure, no side effects, no network. ``execute`` performs the real action
    against the injected Google session (which may be a fake).
    """

    name: str
    card_type: CardType
    params_model: type[BaseModel]
    description: str

    def dry_run(self, params: BaseModel) -> tuple[str, ...]:
        """Preview lines for the approval card. Subclasses must override."""
        raise NotImplementedError

    async def execute(self, params: BaseModel, google_session: GoogleSession) -> ToolResult:
        """Perform the action. Subclasses must override."""
        raise NotImplementedError


class ToolRegistry:
    """Card type -> tool, exhaustively and exclusively."""

    def __init__(self, tools: Sequence[AgentTool]) -> None:
        self._tools_by_card_type: dict[CardType, AgentTool] = {}
        for tool in tools:
            if tool.card_type in self._tools_by_card_type:
                # Two tools for one card type would make execution ambiguous.
                raise ValueError(f"duplicate tool for card type '{tool.card_type}'")
            self._tools_by_card_type[tool.card_type] = tool

    def tool_for_card_type(self, card_type: str) -> AgentTool:
        """The one tool for this card type; deny unknown types."""
        try:
            known = CardType(card_type)
        except ValueError:
            raise UnknownCardTypeError(card_type) from None
        tool = self._tools_by_card_type.get(known)
        if tool is None:
            raise UnknownCardTypeError(card_type)
        return tool

    def registered_card_types(self) -> frozenset[CardType]:
        return frozenset(self._tools_by_card_type)

    def tool_names(self) -> frozenset[str]:
        return frozenset(tool.name for tool in self._tools_by_card_type.values())
