"""Vault trace of an executed action: daily-note line + meeting Actions line.

Purpose: after a card executes, leave the human-readable trail in the
user's own vault — one line in ``Daily/YYYY-MM-DD.md`` and, when the card
belongs to a meeting, one line inside that note's Actions managed region.
Best-effort BY DESIGN: the action already ran, so a trace failure is
returned to the executor (which records it honestly in the result and the
audit row) — never raised, never hidden.
Pipeline position: called by ``card_executor`` on the success path only.

Security invariant: both writers underneath enforce their own fail-closed
rules (single-line entries, managed-region boundaries); this module adds
no write primitive of its own.
"""

import logging
from datetime import UTC, datetime
from pathlib import Path

import aiosqlite

from engine.agents.approval_card_types import ApprovalCardRecord
from engine.agents.meeting_actions_region_appender import append_meeting_actions_line
from engine.agents.tool_registry import ToolResult
from engine.vault.daily_note_appender import append_daily_note_line
from engine.vault.vault_errors import VaultWriteError

_logger = logging.getLogger(__name__)


async def write_executed_action_vault_trace(
    connection: aiosqlite.Connection,
    record: ApprovalCardRecord,
    result: ToolResult,
    vault_root: Path | None,
) -> str | None:
    """Write both trace lines; return the plain-voice failure or None."""
    if vault_root is None:
        return "vault not configured — no vault trace written"
    now = datetime.now(tz=UTC)
    line = f"- {now.strftime('%H:%M')} Omni ({record.card_type}): {result.summary_line}"
    try:
        append_daily_note_line(vault_root, date_iso=now.date().isoformat(), line=line)
        note_path = await _meeting_note_path(connection, record, vault_root)
        if note_path is not None:
            append_meeting_actions_line(note_path, line)
        return None
    except (VaultWriteError, OSError) as error:
        _logger.warning("vault trace failed for card %s: %s", record.id, error)
        return str(error)


async def _meeting_note_path(
    connection: aiosqlite.Connection, record: ApprovalCardRecord, vault_root: Path
) -> Path | None:
    """The meeting note's absolute path (0006 ``note_path``), when the card
    belongs to a meeting whose note exists."""
    if record.meeting_id is None:
        return None
    cursor = await connection.execute(
        "SELECT note_path FROM meetings WHERE id = ?", (record.meeting_id,)
    )
    row = await cursor.fetchone()
    await cursor.close()
    if row is None or row[0] is None or not str(row[0]):
        return None
    path = Path(str(row[0]))
    resolved = path if path.is_absolute() else vault_root / path
    return resolved if resolved.exists() else None
