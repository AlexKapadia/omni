"""Registry factory for the approval surface: real vault, or refusal fallback.

Purpose: one place that answers "which tool registry does the approval
surface get for this vault state?". With a configured vault it is exactly
:func:`build_default_tool_registry`; with NO configured vault the two
vault-backed tools are swapped for stand-ins whose previews still work
(``dry_run`` is pure) but whose ``execute`` REFUSES with a plain-voice
reason — nothing may ever be written to an invented vault location.
Pipeline position: called per command by ``approval_cards_gateway`` and
per broadcast by ``approval_card_build_server_wiring``.

Security invariant (fail closed): the fallback path removes the WRITE
capability, never the honesty — a card executed without a vault fails
typed, it does not guess a directory.
"""

from pathlib import Path

from pydantic import BaseModel

from engine.agents.agents_errors import ToolExecutionError
from engine.agents.calendar_create_event_tool import CalendarCreateEventTool
from engine.agents.calendar_find_free_slot_tool import CalendarFindFreeSlotTool
from engine.agents.contacts_upsert_tool import ContactsUpsertTool
from engine.agents.default_tool_registry import build_default_tool_registry
from engine.agents.gmail_create_draft_tool import GmailCreateDraftTool
from engine.agents.tool_registry import AgentTool, ToolRegistry, ToolResult
from engine.agents.vault_write_note_tool import VaultWriteNoteTool
from engine.google.google_session import GoogleSession


class _VaultUnconfiguredRefusalTool(AgentTool):
    """Stand-in for a vault-backed tool when no vault is configured.

    Previews still work (``dry_run`` is pure — it never touches the root the
    template was built with), but ``execute`` REFUSES with a plain-voice
    reason: nothing may ever be written to an invented vault (fail closed).
    """

    def __init__(self, template: AgentTool) -> None:
        self.name = template.name
        self.card_type = template.card_type
        self.params_model = template.params_model
        self.description = template.description
        self._template = template

    def dry_run(self, params: BaseModel) -> tuple[str, ...]:
        return self._template.dry_run(params)

    async def execute(self, params: BaseModel, google_session: GoogleSession) -> ToolResult:
        raise ToolExecutionError(
            self.name,
            "the vault is not configured (set OMNI_VAULT_DIR) — this action needs a vault",
        )


def build_registry_for_vault_root(vault_root: Path | None) -> ToolRegistry:
    """The default registry: the real five tools, or — with no configured
    vault — the same surface with the two vault-backed tools swapped for
    execute-refusing stand-ins (previews stay real, writes stay impossible)."""
    if vault_root is not None:
        return build_default_tool_registry(vault_root)
    # dry_run never reads this path and execute is overridden to refuse.
    placeholder = Path("omni-vault-not-configured")
    return ToolRegistry(
        (
            CalendarCreateEventTool(),
            CalendarFindFreeSlotTool(),
            _VaultUnconfiguredRefusalTool(ContactsUpsertTool(placeholder)),
            _VaultUnconfiguredRefusalTool(VaultWriteNoteTool(placeholder)),
            GmailCreateDraftTool(),
        )
    )
