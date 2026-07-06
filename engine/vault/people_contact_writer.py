"""People contact-card writer — ``People/{Name}.md`` with upsert semantics.

Purpose: create and enrich per-person contact cards: frontmatter fields
(phone / email / company) plus a ``## Meetings`` list of wikilinks to the
meeting notes the person appears in.
Pipeline position: called by the agent executor's contact-upsert tool and
by the meeting finalizer (backlinking attendees).

Security invariants — the upsert is INSERT-ONLY by construction:
- Existing lines are never modified or removed; merging only inserts new
  frontmatter lines (missing keys) and appends new wikilink lines. A field
  the user already set — even to an empty value — is never overwritten
  (user wins; never-drop-user-content invariant enforced in code).
- Files that start a frontmatter block but never close it are ambiguous:
  the merge is refused (fail closed) rather than guessed at.
- Reassembly joins the ORIGINAL lines (keepends), so user line endings and
  a leading BOM survive byte-for-byte.
"""

import re
from collections.abc import Sequence
from pathlib import Path

from engine.vault.atomic_markdown_file_io import read_file_bytes, write_file_atomically
from engine.vault.filename_sanitizer import sanitize_filename_stem
from engine.vault.frontmatter_codec import emit_frontmatter, emit_scalar
from engine.vault.obsidian_wikilink_formatter import format_wikilink
from engine.vault.vault_errors import FrontmatterFormatError
from engine.vault.vault_paths import PEOPLE_FOLDER, ensure_vault_subfolder

_MEETINGS_HEADING = "## Meetings"
# U+FEFF: a leading BOM (some Windows editors add one) is detached before the
# merge and re-attached verbatim, so BOM'd user files round-trip byte-exact.
_LEADING_BOM = chr(0xFEFF)
_TOP_LEVEL_KEY = re.compile(r"([A-Za-z_][A-Za-z0-9_-]*)\s*:")


def upsert_person_note(
    vault_root: Path,
    *,
    name: str,
    phone: str | None = None,
    email: str | None = None,
    company: str | None = None,
    meeting_note_stems: Sequence[str] = (),
) -> Path:
    """Create or enrich ``People/{name}.md``; return the card's path.

    Existing cards get missing frontmatter keys inserted and unseen meeting
    wikilinks appended — nothing else changes (insert-only merge).
    """
    folder = ensure_vault_subfolder(vault_root, PEOPLE_FOLDER)
    path = folder / f"{sanitize_filename_stem(name)}.md"
    fields = {"phone": phone, "email": email, "company": company}
    links = [format_wikilink(stem) for stem in meeting_note_stems]
    if not path.exists():
        write_file_atomically(path, _render_new_card(name, fields, links))
        return path
    original = read_file_bytes(path)
    merged = _merge_into_existing_card(original.decode("utf-8"), fields, links)
    if merged.encode("utf-8") != original:  # idempotency: no-op merge, no disk churn
        write_file_atomically(path, merged)
    return path


def _render_new_card(name: str, fields: dict[str, str | None], links: list[str]) -> str:
    """Full card content for a person we have never written before."""
    frontmatter = emit_frontmatter(fields)  # None fields are omitted
    body = f"\n# {name}\n\n{_MEETINGS_HEADING}\n\n"
    body += "".join(f"- {link}\n" for link in links)
    return frontmatter + body


def _merge_into_existing_card(
    text: str, fields: dict[str, str | None], links: list[str]
) -> str:
    """Insert-only merge: new frontmatter keys + new wikilinks, nothing edited."""
    bom, text = (
        (_LEADING_BOM, text[1:]) if text.startswith(_LEADING_BOM) else ("", text)
    )
    lines = text.splitlines(keepends=True)
    lines = _insert_missing_frontmatter_keys(lines, fields)
    lines = _append_missing_meeting_links(lines, links)
    return bom + "".join(lines)


def _insert_missing_frontmatter_keys(
    lines: list[str], fields: dict[str, str | None]
) -> list[str]:
    """Insert ``key: value`` lines for absent keys just before the closing ``---``."""
    wanted = {key: value for key, value in fields.items() if value is not None}
    if not wanted:
        return lines
    if not lines or lines[0].rstrip("\r\n") != "---":
        # No frontmatter: PREPEND a fresh block (adds content, edits nothing).
        return emit_frontmatter(wanted).splitlines(keepends=True) + lines
    close_index = next(
        (i for i in range(1, len(lines)) if lines[i].rstrip("\r\n") == "---"), None
    )
    if close_index is None:
        # fail-closed: unterminated frontmatter is ambiguous — refuse to merge.
        raise FrontmatterFormatError("existing frontmatter never closes; upsert refused")
    existing_keys = {
        match.group(1)
        for line in lines[1:close_index]
        if (match := _TOP_LEVEL_KEY.match(line))
    }
    # Insert-only: keys the user already has are NEVER touched (user wins).
    new_lines = [
        f"{key}: {emit_scalar(value)}\n"
        for key, value in wanted.items()
        if key not in existing_keys
    ]
    return lines[:close_index] + new_lines + lines[close_index:]


def _append_missing_meeting_links(lines: list[str], links: list[str]) -> list[str]:
    """Append wikilink list items not already present anywhere in the card."""
    text = "".join(lines)
    missing = [
        link
        for link in links
        # An aliased link to the same target also counts as present.
        if link not in text and f"{link[:-2]}|" not in text
    ]
    if not missing:
        return lines
    if lines and not lines[-1].endswith(("\n", "\r")):
        # Complete the user's final line before appending (a bare append
        # would splice our link onto their text — worse than adding "\n").
        lines[-1] += "\n"
    heading_index = next(
        (i for i, line in enumerate(lines) if line.rstrip("\r\n") == _MEETINGS_HEADING), None
    )
    new_items = [f"- {link}\n" for link in missing]
    if heading_index is None:
        return [*lines, f"\n{_MEETINGS_HEADING}\n\n", *new_items]
    insert_at = heading_index + 1
    i = heading_index + 1
    while i < len(lines):  # walk past the existing list; insert after its last item
        stripped = lines[i].strip()
        if stripped.startswith("- "):
            insert_at = i + 1
        elif stripped != "":
            break
        i += 1
    return lines[:insert_at] + new_items + lines[insert_at:]
