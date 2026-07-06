"""Builds the standard five-tool registry — the whole M4 capability set.

Purpose: one factory the server wiring calls to assemble the registry.
Listing the tools HERE, exhaustively, is the point: what Omni can do is
readable in one screen, and what is not listed cannot happen (deny by
default). Note there is no send tool — drafts are the entire Gmail
capability (draft-only invariant).
Pipeline position: called once at engine startup (deferred wiring); the
result is handed to ``card_executor``.
"""

from pathlib import Path

from engine.agents.calendar_create_event_tool import CalendarCreateEventTool
from engine.agents.calendar_find_free_slot_tool import CalendarFindFreeSlotTool
from engine.agents.contacts_upsert_tool import ContactsUpsertTool
from engine.agents.gmail_create_draft_tool import GmailCreateDraftTool
from engine.agents.tool_registry import ToolRegistry
from engine.agents.vault_write_note_tool import VaultWriteNoteTool


def build_default_tool_registry(vault_root: Path) -> ToolRegistry:
    """The five tools, one per card type. Nothing else exists."""
    return ToolRegistry(
        (
            CalendarCreateEventTool(),
            CalendarFindFreeSlotTool(),
            ContactsUpsertTool(vault_root),
            VaultWriteNoteTool(vault_root),
            GmailCreateDraftTool(),
        )
    )
