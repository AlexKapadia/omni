"""Meeting note writer — ``Meetings/YYYY-MM-DD {title}.md``.

Purpose: create the per-meeting note (frontmatter + My Notes + managed
Enhanced Notes / Actions / Transcript sections) and expose the ONLY three
update operations that exist for it — replacing the inside of each managed
region. ``## My Notes`` is user territory: written once at creation, never
touched again by any code path in this package.
Pipeline position: called by the M2 enhancement pipeline (enhanced notes,
actions) and the live-capture finalizer (transcript).

Security invariants:
- Updates go exclusively through ``rewrite_managed_region`` — there is no
  API here that can modify user-authored bytes (information boundary
  enforced in the writer, not by convention).
- Creation collision-suffixes the filename, so an existing note (user's or
  a previous meeting's) is never overwritten.
"""

from collections.abc import Sequence
from pathlib import Path

from engine.vault.atomic_markdown_file_io import read_file_bytes, write_file_atomically
from engine.vault.filename_sanitizer import next_available_note_path, sanitize_filename_stem
from engine.vault.frontmatter_codec import emit_frontmatter
from engine.vault.managed_region_rewriter import (
    REGION_ACTIONS,
    REGION_ENHANCED_NOTES,
    REGION_TRANSCRIPT,
    render_managed_region,
    rewrite_managed_region,
)
from engine.vault.vault_paths import MEETINGS_FOLDER, ensure_vault_subfolder

_ENHANCED_PLACEHOLDER = "_Enhanced notes will appear here after the meeting._"
_ACTIONS_PLACEHOLDER = "_No actions yet._"


def create_meeting_note(
    vault_root: Path,
    *,
    title: str,
    date_iso: str,
    attendees: Sequence[str] = (),
    tags: Sequence[str] = ("meeting",),
    calendar_event_id: str | None = None,
    disclosed: bool = False,
    my_notes: str = "",
    transcript_lines: Sequence[str] = (),
) -> Path:
    """Create ``Meetings/{date} {title}.md``; return the path actually written.

    ``date_iso`` is ``YYYY-MM-DD``. A filename collision gets a `` (n)``
    suffix — creation never overwrites (never-edit-user-content invariant).
    """
    frontmatter = emit_frontmatter(
        {
            "date": date_iso,
            "title": title,
            "attendees": list(attendees),
            "tags": list(tags),
            "calendar_event_id": calendar_event_id,  # omitted when None
            "disclosed": disclosed,
        }
    )
    body = (
        f"\n## My Notes\n\n{my_notes.rstrip()}\n\n"
        f"## Enhanced Notes\n\n"
        f"{render_managed_region(REGION_ENHANCED_NOTES, _ENHANCED_PLACEHOLDER)}\n\n"
        f"## Actions\n\n"
        f"{render_managed_region(REGION_ACTIONS, _ACTIONS_PLACEHOLDER)}\n\n"
        f"## Transcript\n\n"
        f"{render_managed_region(REGION_TRANSCRIPT, format_transcript_callout(transcript_lines))}\n"
    )
    folder = ensure_vault_subfolder(vault_root, MEETINGS_FOLDER)
    stem = sanitize_filename_stem(f"{date_iso} {title}")
    path = next_available_note_path(folder, stem)
    write_file_atomically(path, frontmatter + body)
    return path


def format_transcript_callout(transcript_lines: Sequence[str]) -> str:
    """Render the collapsed ``> [!note]- Transcript`` callout body.

    Every transcript line is quoted (``> ``); embedded newlines are split so
    a multi-line segment cannot escape the callout (untrusted-content
    containment). Empty transcript renders an honest placeholder.
    """
    flat: list[str] = []
    for line in transcript_lines:
        flat.extend(line.split("\n"))
    if not flat:
        return "> [!note]- Transcript\n> _No transcript captured._"
    quoted = "\n".join(f"> {line}".rstrip() for line in flat)
    return f"> [!note]- Transcript\n{quoted}"


def update_meeting_enhanced_notes(note_path: Path, enhanced_markdown: str) -> Path:
    """Replace the Enhanced Notes managed region. All other bytes preserved."""
    return _rewrite_region(note_path, REGION_ENHANCED_NOTES, enhanced_markdown)


def update_meeting_actions(note_path: Path, actions_markdown: str) -> Path:
    """Replace the Actions managed region. All other bytes preserved."""
    return _rewrite_region(note_path, REGION_ACTIONS, actions_markdown)


def update_meeting_transcript(note_path: Path, transcript_lines: Sequence[str]) -> Path:
    """Replace the Transcript managed region with a fresh collapsed callout."""
    callout = format_transcript_callout(transcript_lines)
    return _rewrite_region(note_path, REGION_TRANSCRIPT, callout)


def _rewrite_region(note_path: Path, region_id: str, inner_markdown: str) -> Path:
    """Read, rewrite one region (fail closed on corruption), write atomically."""
    original = read_file_bytes(note_path)
    updated = rewrite_managed_region(original, region_id, inner_markdown)
    if updated != original:  # idempotency: identical content -> no disk churn
        write_file_atomically(note_path, updated)
    return note_path
