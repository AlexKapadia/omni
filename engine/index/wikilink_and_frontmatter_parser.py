"""Markdown structure extraction: wikilinks, frontmatter, and headings.

Purpose: turn one raw markdown note into the structural facts the index
layer needs — ``[[wikilinks]]`` (with aliases), frontmatter fields, and
ATX headings with 1-based line numbers.
Pipeline position: first stage of indexing; the chunker and the vault
indexer both consume its output.

Untrusted-input discipline: vault notes are USER/EXTERNAL content. This
parser never executes, resolves, or interpolates anything it extracts —
everything returned is inert data. Unlike ``engine.vault.frontmatter_codec``
(which fails closed on the narrow schema Omni itself WRITES), this parser
is deliberately LENIENT: arbitrary user YAML must never block indexing, so
unparseable frontmatter lines are skipped, not fatal.

Documented semantics (tested):
- Wikilinks: ``[[Target]]``, ``[[Target|alias]]``, ``[[Target#Heading]]``.
  The innermost bracket pair wins on nested brackets (``[[a [[b]] c]]``
  yields ``b``). Links inside fenced code blocks (``` / ~~~) and inline
  code spans are NOT extracted — Obsidian does not render them there.
- Headings: ATX only (``#`` .. ``######`` + space), ignored inside fences.
- Frontmatter: a leading ``---`` fence closed by ``---``/``...``. Supports
  ``key: value`` scalars and ``- item`` block lists; values are kept as
  raw strings (surrounding quotes stripped). Anything else is skipped.
"""

import re
from dataclasses import dataclass, field

# Innermost non-greedy pair: forbidding [ ] inside guarantees that nested
# brackets resolve to the innermost link, matching Obsidian's renderer.
_WIKILINK_PATTERN = re.compile(r"\[\[([^\[\]]+?)\]\]")
_HEADING_PATTERN = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
_FENCE_PATTERN = re.compile(r"^\s{0,3}(```|~~~)")
_INLINE_CODE_PATTERN = re.compile(r"`[^`\n]*`")
_FRONTMATTER_KEY_PATTERN = re.compile(r"^([A-Za-z_][A-Za-z0-9_-]*)\s*:\s*(.*)$")


@dataclass(frozen=True)
class Wikilink:
    """One extracted wikilink: target note name, optional alias, source line."""

    target: str  # note name as written, alias and #heading stripped
    alias: str | None
    line: int  # 1-based


@dataclass(frozen=True)
class Heading:
    """One ATX heading with its nesting level and 1-based source line."""

    level: int
    text: str
    line: int


@dataclass(frozen=True)
class ParsedNote:
    """Structural facts of one note; all content is inert, untrusted data."""

    frontmatter: dict[str, str | list[str]] = field(default_factory=dict)
    body_start_line: int = 1  # 1-based first line AFTER the frontmatter block
    headings: list[Heading] = field(default_factory=list)
    wikilinks: list[Wikilink] = field(default_factory=list)


def _code_fence_line_mask(lines: list[str]) -> list[bool]:
    """True for lines inside (or opening/closing) a fenced code block."""
    mask: list[bool] = []
    open_fence: str | None = None
    for line in lines:
        match = _FENCE_PATTERN.match(line)
        if open_fence is None:
            if match:
                open_fence = match.group(1)
                mask.append(True)
            else:
                mask.append(False)
        else:
            mask.append(True)
            if match and match.group(1) == open_fence:
                open_fence = None
    return mask


def parse_frontmatter_lenient(text: str) -> tuple[dict[str, str | list[str]], int]:
    """Best-effort frontmatter parse; returns ``(fields, body_start_line)``.

    Never raises on malformed content (untrusted input must not block
    indexing): bad lines are skipped, an unclosed fence means the note has
    no frontmatter at all. ``body_start_line`` is 1-based.
    """
    lines = text.split("\n")
    if not lines or lines[0].rstrip("\r").strip() != "---":
        return {}, 1
    fields: dict[str, str | list[str]] = {}
    pending_list_key: str | None = None
    for index in range(1, len(lines)):
        line = lines[index].rstrip("\r")
        if line.strip() in ("---", "..."):
            return fields, index + 2  # line AFTER the closing fence, 1-based
        stripped = line.strip()
        if pending_list_key is not None and stripped.startswith("- "):
            existing = fields[pending_list_key]
            if isinstance(existing, list):
                existing.append(_strip_quotes(stripped[2:].strip()))
            continue
        pending_list_key = None
        match = _FRONTMATTER_KEY_PATTERN.match(line)
        if not match or match.group(1) in fields:
            continue  # lenient: skip unparseable/duplicate lines, never fail
        key, raw_value = match.group(1), match.group(2).strip()
        if raw_value == "":
            fields[key] = []
            pending_list_key = key
        elif raw_value.startswith("[") and raw_value.endswith("]"):
            inner = raw_value[1:-1].strip()
            fields[key] = (
                [_strip_quotes(item.strip()) for item in inner.split(",")] if inner else []
            )
        else:
            fields[key] = _strip_quotes(raw_value)
    return {}, 1  # fence never closed: treat the whole note as body


def _strip_quotes(value: str) -> str:
    """Strip one layer of matching surrounding quotes; content stays raw."""
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
        return value[1:-1]
    return value


def parse_headings(text: str, first_line: int = 1) -> list[Heading]:
    """Extract ATX headings (with 1-based line numbers), skipping code fences.

    ``first_line`` lets callers scan only the body while keeping whole-file
    line numbers (pass the body's 1-based starting line).
    """
    lines = text.split("\n")
    fence_mask = _code_fence_line_mask(lines)
    headings: list[Heading] = []
    for offset, line in enumerate(lines):
        if fence_mask[offset]:
            continue
        match = _HEADING_PATTERN.match(line.rstrip("\r"))
        if match:
            headings.append(
                Heading(level=len(match.group(1)), text=match.group(2), line=first_line + offset)
            )
    return headings


def parse_wikilinks(text: str, first_line: int = 1) -> list[Wikilink]:
    """Extract wikilinks with 1-based line numbers.

    Fenced code blocks are skipped whole; inline code spans are blanked
    per-line before matching (Obsidian renders neither as a link).
    """
    lines = text.split("\n")
    fence_mask = _code_fence_line_mask(lines)
    links: list[Wikilink] = []
    for offset, line in enumerate(lines):
        if fence_mask[offset]:
            continue
        scannable = _INLINE_CODE_PATTERN.sub(lambda m: " " * len(m.group(0)), line)
        for match in _WIKILINK_PATTERN.finditer(scannable):
            inner = match.group(1)
            target_part, _, alias_part = inner.partition("|")
            target = target_part.split("#", 1)[0].strip()
            if not target:
                continue  # pure-anchor links ([[#Heading]]) target no note
            alias = alias_part.strip() or None
            links.append(Wikilink(target=target, alias=alias, line=first_line + offset))
    return links


def parse_note(text: str) -> ParsedNote:
    """Parse one markdown note into frontmatter + headings + wikilinks."""
    frontmatter, body_start_line = parse_frontmatter_lenient(text)
    body = "\n".join(text.split("\n")[body_start_line - 1 :])
    return ParsedNote(
        frontmatter=frontmatter,
        body_start_line=body_start_line,
        headings=parse_headings(body, first_line=body_start_line),
        wikilinks=parse_wikilinks(body, first_line=body_start_line),
    )
