"""Omni vault writers — the permanent, human-readable Obsidian layer.

Purpose: every markdown artifact Omni produces (meeting notes, contact
cards, dictation notes, daily-log lines) is written through this package
and nothing else. It is the single enforcement point for the vault's
information boundary.

Pipeline position: downstream of STT/enhancement (M2 calls the meeting
writers) and of the agent executor (daily-log lines per executed action);
upstream only of the user's own Obsidian vault on disk.

Security invariants upheld package-wide (enforced in code, not convention):
- Omni NEVER edits user-authored text. Writers only create new files,
  append new lines, or replace the inside of ``<!-- omni:managed:<id> -->``
  regions; every byte outside the markers is preserved exactly.
- Marker corruption (missing/duplicated/nested markers) fails closed:
  the write is refused and the file on disk is left untouched.
- All writes are write-then-rename (temp file + ``os.replace``) so a
  crash, sync client, or an Obsidian-held handle never yields a
  half-written note.
"""

from engine.vault.daily_note_appender import append_daily_note_line
from engine.vault.inbox_dictation_writer import create_inbox_dictation_note
from engine.vault.managed_region_rewriter import (
    REGION_ACTIONS,
    REGION_ENHANCED_NOTES,
    REGION_TRANSCRIPT,
)
from engine.vault.meeting_note_writer import (
    create_meeting_note,
    update_meeting_actions,
    update_meeting_enhanced_notes,
    update_meeting_transcript,
)
from engine.vault.people_contact_writer import upsert_person_note
from engine.vault.vault_errors import (
    FrontmatterFormatError,
    ManagedRegionCorruptionError,
    VaultFileLockedError,
    VaultNotConfiguredError,
    VaultWriteError,
)
from engine.vault.vault_paths import resolve_vault_root

__all__ = [
    "REGION_ACTIONS",
    "REGION_ENHANCED_NOTES",
    "REGION_TRANSCRIPT",
    "FrontmatterFormatError",
    "ManagedRegionCorruptionError",
    "VaultFileLockedError",
    "VaultNotConfiguredError",
    "VaultWriteError",
    "append_daily_note_line",
    "create_inbox_dictation_note",
    "create_meeting_note",
    "resolve_vault_root",
    "update_meeting_actions",
    "update_meeting_enhanced_notes",
    "update_meeting_transcript",
    "upsert_person_note",
]
