"""Daily-note appender — one log line per meeting / executed action.

Purpose: append single lines to ``Daily/YYYY-MM-DD.md`` (folder
configurable per call), creating the day's note if absent. This is the
human-readable trace of what Omni did each day, alongside the append-only
audit database.
Pipeline position: called by the meeting finalizer and the agent executor
after each executed (approval-carded) action.

Security invariants:
- Append-only by construction: existing bytes are preserved verbatim (the
  only addition is a terminating newline if the user's last line lacked
  one); user-authored text is never edited.
- A log line containing newlines is refused (fail closed) — a crafted
  multi-line "line" could otherwise forge additional log entries.
"""

from pathlib import Path

from engine.vault.atomic_markdown_file_io import read_file_bytes, write_file_atomically
from engine.vault.filename_sanitizer import sanitize_filename_stem
from engine.vault.vault_errors import VaultWriteError
from engine.vault.vault_paths import DAILY_FOLDER, ensure_vault_subfolder


def append_daily_note_line(
    vault_root: Path,
    *,
    date_iso: str,
    line: str,
    daily_folder_name: str = DAILY_FOLDER,
) -> Path:
    """Append ``line`` to ``{daily_folder_name}/{date_iso}.md``; create if absent.

    Returns the daily note's path. Raises ``VaultWriteError`` if ``line``
    spans multiple lines (log-forging defence, fail closed).
    """
    if "\n" in line or "\r" in line:
        # fail-closed: one call appends exactly one line — no entry forging.
        raise VaultWriteError("daily-note lines must be single-line; write refused")
    folder = ensure_vault_subfolder(vault_root, daily_folder_name)
    path = folder / f"{sanitize_filename_stem(date_iso)}.md"
    if not path.exists():
        write_file_atomically(path, f"# {date_iso}\n\n{line}\n")
        return path
    original = read_file_bytes(path)
    # Complete the user's final line if it lacks a terminator; a bare append
    # would splice our entry onto their text (worse than adding "\n").
    separator = b"" if (not original or original.endswith((b"\n", b"\r"))) else b"\n"
    write_file_atomically(path, original + separator + line.encode("utf-8") + b"\n")
    return path
