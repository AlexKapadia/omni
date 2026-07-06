"""Filename sanitization for vault notes (Windows + Obsidian rules).

Purpose: turn arbitrary user/meeting titles and person names into note-file
stems that are (a) legal on Windows/NTFS and OneDrive, and (b) usable as
Obsidian wikilink targets. Also provides collision suffixing so a new note
never overwrites an existing one.
Pipeline position: called by every writer that creates a note file.

Security invariants:
- Collision suffixing means note CREATION can never clobber an existing
  file (never-edit-user-content, enforced at the path level).
- Titles are untrusted input: control characters, path separators, and
  reserved device names are neutralised so a hostile title cannot escape
  the vault folder or target a device file.
"""

import re
from pathlib import Path

# Windows-illegal characters plus path separators (untrusted-title defence),
# and Obsidian link-breaking characters ([, ], |, #, ^) — these stems become
# wikilink targets, so both rule sets apply.
_FORBIDDEN_CHARS = re.compile(r'[<>:"/\\|?*\[\]#^\x00-\x1f\x7f]')

# Reserved DOS device names: illegal as a basename OR as the part before the
# first dot ("CON.md" is still the CON device), case-insensitive.
_RESERVED_BASENAMES = frozenset(
    {"CON", "PRN", "AUX", "NUL"}
    | {f"COM{n}" for n in range(1, 10)}
    | {f"LPT{n}" for n in range(1, 10)}
)

# Stem length cap (code points). Conservative: leaves headroom for the vault
# path + folder + " (n).md" suffix under Windows' 260-char MAX_PATH.
DEFAULT_MAX_STEM_LENGTH = 120

_FALLBACK_STEM = "Untitled"


def sanitize_filename_stem(raw_title: str, *, max_length: int = DEFAULT_MAX_STEM_LENGTH) -> str:
    """Sanitize an arbitrary title into a safe note-file stem (no extension).

    Rules applied, in order: forbidden characters -> space; whitespace runs
    collapsed; trailing dots/spaces stripped (Windows silently drops them,
    which would alias two distinct titles); reserved device names get a
    trailing underscore; length capped; empty result falls back to
    ``Untitled``. Unicode (CJK, emoji, RTL) passes through untouched.
    """
    cleaned = _FORBIDDEN_CHARS.sub(" ", raw_title)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    # Windows strips trailing dots/spaces itself; strip them here so the name
    # we choose is the name that actually lands on disk (no silent aliasing).
    cleaned = cleaned.rstrip(". ")
    if len(cleaned) > max_length:
        cleaned = cleaned[:max_length].rstrip(". ")
    if not cleaned:
        return _FALLBACK_STEM
    # Reserved-device defence: "CON" or "CON.anything" would address a device,
    # so the FIRST SEGMENT itself must change (a suffix after the dot won't).
    first_segment, dot, rest = cleaned.partition(".")
    if first_segment.upper() in _RESERVED_BASENAMES:
        cleaned = f"{first_segment}_{dot}{rest}"
    return cleaned


def next_available_note_path(folder: Path, stem: str, extension: str = ".md") -> Path:
    """First non-existing path for ``stem`` in ``folder``, suffixing `` (n)``.

    ``stem`` must already be sanitized. Existence is checked case-insensitively
    via a directory listing because NTFS is case-insensitive — ``exists()``
    alone would miss a case-variant collision on case-sensitive filesystems
    that later syncs to a case-insensitive one.
    """
    try:
        existing_lower = {entry.name.lower() for entry in folder.iterdir()}
    except FileNotFoundError:
        existing_lower = set()
    candidate = f"{stem}{extension}"
    counter = 2
    while candidate.lower() in existing_lower:
        candidate = f"{stem} ({counter}){extension}"
        counter += 1
    return folder / candidate
