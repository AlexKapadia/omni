"""Inbox dictation-note writer — ``Inbox/{title}.md``.

Purpose: land push-to-talk dictation as a new note in the vault's Inbox
folder with honest provenance frontmatter (``source: dictation``).
Pipeline position: called by the dictation flow after STT finalizes.

Security invariant: creation-only — collision suffixing guarantees an
existing note is never overwritten (never-edit-user-content), and the
untrusted dictated title is sanitized before it becomes a filename.
"""

from pathlib import Path

from engine.vault.atomic_markdown_file_io import write_file_atomically
from engine.vault.filename_sanitizer import next_available_note_path, sanitize_filename_stem
from engine.vault.frontmatter_codec import emit_frontmatter
from engine.vault.vault_paths import INBOX_FOLDER, ensure_vault_subfolder


def create_inbox_dictation_note(
    vault_root: Path,
    *,
    title: str,
    body_markdown: str,
    date_iso: str,
) -> Path:
    """Create ``Inbox/{title}.md``; return the path actually written.

    ``date_iso`` is ``YYYY-MM-DD``. Filename collisions get a `` (n)``
    suffix so nothing is ever overwritten.
    """
    frontmatter = emit_frontmatter({"date": date_iso, "source": "dictation"})
    content = f"{frontmatter}\n{body_markdown.rstrip()}\n"
    folder = ensure_vault_subfolder(vault_root, INBOX_FOLDER)
    path = next_available_note_path(folder, sanitize_filename_stem(title))
    write_file_atomically(path, content)
    return path
