"""Obsidian wikilink formatting for vault notes.

Purpose: render ``[[target]]`` / ``[[target|alias]]`` links whose targets
are guaranteed resolvable — link targets are note-file stems, so they are
pushed through the same sanitizer that names the files (links can never
point at a name the writer could not have created).
Pipeline position: used by the people writer (meeting backlinks) and by
daily-note lines that reference meeting notes.

Security invariant: link-breaking characters (``[ ] | # ^``) are removed by
sanitization, so an untrusted title cannot forge extra links, aliases, or
heading/block references inside a link it appears in.
"""

from engine.vault.filename_sanitizer import sanitize_filename_stem


def format_wikilink(note_stem: str, alias: str | None = None) -> str:
    """Render a wikilink to a note stem, optionally aliased.

    The target is re-sanitized defensively (idempotent for already-sanitized
    stems). Aliases have ``[``, ``]`` and ``|`` stripped — they are display
    text and must not terminate or split the link.
    """
    target = sanitize_filename_stem(note_stem)
    if alias is None:
        return f"[[{target}]]"
    safe_alias = alias.replace("[", "").replace("]", "").replace("|", "").strip()
    if not safe_alias or safe_alias == target:
        return f"[[{target}]]"
    return f"[[{target}|{safe_alias}]]"
