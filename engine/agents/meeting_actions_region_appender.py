"""Append one executed-action line to a meeting note's Actions region.

Purpose: the human-readable trace of what Omni DID, inside the meeting note
it did it for. Appending means: read the current managed-region content,
add one line at the bottom, and write the region back through
``rewrite_managed_region`` — so all the fail-closed corruption checks and
the byte-exact preservation of user text apply unchanged.
Pipeline position: called by ``card_executor`` after a successful
execution, alongside the daily-note line and the audit row.

Security invariants:
- Writes go exclusively through the managed-region rewriter (information
  boundary enforced in the writer, not by convention).
- A line containing newlines is refused (fail closed) — one call appends
  exactly one line, mirroring the daily-note appender's forging defence.
"""

from pathlib import Path

from engine.vault.atomic_markdown_file_io import read_file_bytes
from engine.vault.managed_region_rewriter import (
    REGION_ACTIONS,
    close_marker,
    open_marker,
)
from engine.vault.meeting_note_writer import update_meeting_actions
from engine.vault.vault_errors import ManagedRegionCorruptionError, VaultWriteError

# The placeholder the meeting-note writer creates the region with; it is
# dropped when the first real line lands (it is scaffolding, not content).
_EMPTY_ACTIONS_PLACEHOLDERS = frozenset(
    {"_No actions yet._", "_No actions detected in this meeting._"}
)


def _current_actions_inner_text(note_bytes: bytes) -> str:
    """The text currently inside the Actions region (fail closed on
    marker ambiguity, mirroring the rewriter's rules)."""
    open_line = open_marker(REGION_ACTIONS).encode("utf-8")
    close_line = close_marker(REGION_ACTIONS).encode("utf-8")
    lines = note_bytes.splitlines()
    open_indices = [i for i, line in enumerate(lines) if line.strip() == open_line]
    close_indices = [i for i, line in enumerate(lines) if line.strip() == close_line]
    if len(open_indices) != 1 or len(close_indices) != 1 or close_indices[0] <= open_indices[0]:
        raise ManagedRegionCorruptionError(
            "actions region markers are ambiguous — append refused"
        )
    inner = lines[open_indices[0] + 1 : close_indices[0]]
    return b"\n".join(inner).decode("utf-8", errors="replace")


def append_meeting_actions_line(note_path: Path, line: str) -> Path:
    """Append ``line`` to the note's Actions managed region.

    Raises ``VaultWriteError`` on a multi-line "line" (entry forging
    defence) and ``ManagedRegionCorruptionError`` when the region is
    ambiguous (fail closed; the rewriter re-checks everything again).
    """
    if "\n" in line or "\r" in line:
        # fail-closed: one call appends exactly one line — no entry forging.
        raise VaultWriteError("actions-region lines must be single-line; write refused")
    current = _current_actions_inner_text(read_file_bytes(note_path)).strip()
    if current in _EMPTY_ACTIONS_PLACEHOLDERS:
        current = ""  # first real line replaces the placeholder scaffolding
    new_inner = f"{current}\n{line}" if current else line
    return update_meeting_actions(note_path, new_inner)
