"""Heading-aware markdown chunking with deterministic contextual prefixes.

Purpose: split one note into retrieval chunks that (a) never cross heading
boundaries, (b) respect sentence boundaries when a section must be split,
and (c) carry a DETERMINISTIC contextual prefix (title + heading breadcrumb
+ date + key frontmatter) — the zero-LLM-cost variant of Anthropic's
Contextual Retrieval (2024) evidence, per the M3 recommendation.
Pipeline position: parser output in, ``Chunk`` rows out; the vault indexer
persists them and the embedder/FTS index ``contextualized_text``.

Citation contract (security/fidelity invariant): ``chunk.text`` is ALWAYS
the exact source slice ``document[char_start:char_end]``, and line numbers
are 1-based inclusive — the UI renders ``note_path · L<start>-<end>`` and
that span must contain exactly the cited words. Content is untrusted data;
nothing here interprets it.

Token heuristic (documented, deliberate): tokens ≈ ceil(chars / 4) — the
standard English approximation — until a real tokenizer dependency lands
(tracked in docs/progress/pending-deps.txt). Limits below are expressed in
tokens and enforced via this heuristic:
- MAX 400 tokens (1600 chars) per chunk — a MAXIMUM, not a grid: sections
  smaller than the cap become one chunk, never padded or merged across
  headings.
- MAX 80 tokens (320 chars) of sentence-aligned overlap between adjacent
  chunks of the same section.
"""

import math
import re
from collections.abc import Mapping
from dataclasses import dataclass

from engine.index.wikilink_and_frontmatter_parser import Heading, parse_note

MAX_CHUNK_TOKENS = 400
MAX_OVERLAP_TOKENS = 80
_CHARS_PER_TOKEN = 4  # documented heuristic: tokens ≈ ceil(chars / 4)
MAX_CHUNK_CHARS = MAX_CHUNK_TOKENS * _CHARS_PER_TOKEN
MAX_OVERLAP_CHARS = MAX_OVERLAP_TOKENS * _CHARS_PER_TOKEN

# Key frontmatter surfaced in the contextual prefix, in this fixed order —
# order is part of the deterministic-prefix contract and is tested exactly.
KEY_FRONTMATTER_KEYS = ("type", "tags", "people", "company", "status")

# Sentence boundary: terminal punctuation + whitespace, or a blank line.
_SENTENCE_BOUNDARY = re.compile(r"(?<=[.!?])\s+|\n{2,}")


def estimate_tokens(text: str) -> int:
    """Heuristic token count: ceil(chars / 4); empty text is 0 tokens."""
    return math.ceil(len(text) / _CHARS_PER_TOKEN)


@dataclass(frozen=True)
class Chunk:
    """One retrievable chunk with its exact citation span."""

    note_path: str
    source_type: str  # 'vault' | 'transcript'
    note_title: str
    heading_path: str  # ' > '-joined breadcrumb, '' when outside any heading
    line_start: int  # 1-based inclusive
    line_end: int  # 1-based inclusive
    char_start: int  # 0-based; text == document[char_start:char_end]
    char_end: int  # exclusive
    text: str
    contextualized_text: str


def build_contextual_prefix(
    note_title: str,
    heading_path: str,
    note_date: str | None,
    frontmatter: Mapping[str, str | list[str]],
) -> str:
    """Deterministic contextual prefix — the exact-format contract.

    Line order is fixed: Note, Section (when in a heading), Date (when
    known), then KEY_FRONTMATTER_KEYS in declaration order. Identical
    inputs always yield the identical string (tested for exactness).
    """
    lines = [f"Note: {note_title}"]
    if heading_path:
        lines.append(f"Section: {heading_path}")
    if note_date:
        lines.append(f"Date: {note_date}")
    for key in KEY_FRONTMATTER_KEYS:
        value = frontmatter.get(key)
        if value is None:
            continue
        rendered = ", ".join(value) if isinstance(value, list) else value
        if rendered:
            lines.append(f"{key.capitalize()}: {rendered}")
    return "\n".join(lines)


def _line_offsets(document: str) -> list[int]:
    """Char offset of the start of each line (index i -> line i+1)."""
    offsets = [0]
    for index, char in enumerate(document):
        if char == "\n":
            offsets.append(index + 1)
    return offsets


def _line_of_offset(line_starts: list[int], offset: int) -> int:
    """1-based line number containing the given char offset (binary search)."""
    lo, hi = 0, len(line_starts) - 1
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if line_starts[mid] <= offset:
            lo = mid
        else:
            hi = mid - 1
    return lo + 1


def _sections(
    document: str, headings: list[Heading], body_start_line: int, line_starts: list[int]
) -> list[tuple[str, int, int]]:
    """Split the body into (heading_path, char_start, char_end) sections.

    A section spans from just after its heading line to the next heading
    (any level). The breadcrumb is the stack of enclosing headings.
    """
    if body_start_line - 1 < len(line_starts):
        body_start_char = line_starts[body_start_line - 1]
    else:
        body_start_char = len(document)
    sections: list[tuple[str, int, int]] = []
    stack: list[Heading] = []
    cursor = body_start_char
    breadcrumb = ""
    for heading in headings:
        if cursor < len(document):
            sections.append((breadcrumb, cursor, line_starts[heading.line - 1]))
        while stack and stack[-1].level >= heading.level:
            stack.pop()
        stack.append(heading)
        breadcrumb = " > ".join(h.text for h in stack)
        # Section content starts on the line after the heading line.
        cursor = (
            line_starts[heading.line] if heading.line < len(line_starts) else len(document)
        )
    sections.append((breadcrumb, cursor, len(document)))
    return sections


def _sentence_spans(document: str, start: int, end: int) -> list[tuple[int, int]]:
    """Sentence-ish spans within [start, end): boundaries at ., !, ? or blank
    lines. A span longer than MAX_CHUNK_CHARS is hard-split (unsplittable
    walls of text must still chunk)."""
    spans: list[tuple[int, int]] = []
    cursor = start
    for match in _SENTENCE_BOUNDARY.finditer(document, start, end):
        if match.end() > end:
            break
        if match.start() > cursor:
            spans.append((cursor, match.end()))
        cursor = match.end()
    if cursor < end:
        spans.append((cursor, end))
    hard_split: list[tuple[int, int]] = []
    for span_start, span_end in spans:
        while span_end - span_start > MAX_CHUNK_CHARS:
            hard_split.append((span_start, span_start + MAX_CHUNK_CHARS))
            span_start += MAX_CHUNK_CHARS
        hard_split.append((span_start, span_end))
    return hard_split


def _trim(document: str, start: int, end: int) -> tuple[int, int]:
    """Shrink a span to exclude leading/trailing whitespace (offsets stay exact)."""
    while start < end and document[start] in " \t\r\n":
        start += 1
    while end > start and document[end - 1] in " \t\r\n":
        end -= 1
    return start, end


def _split_section(document: str, start: int, end: int) -> list[tuple[int, int]]:
    """Split one section into chunk spans ≤ MAX_CHUNK_CHARS with sentence-
    aligned overlap ≤ MAX_OVERLAP_CHARS. Spans are contiguous source slices
    (overlap = the next span starts at an earlier sentence boundary)."""
    start, end = _trim(document, start, end)
    if start >= end:
        return []
    if end - start <= MAX_CHUNK_CHARS:
        return [(start, end)]
    sentences = _sentence_spans(document, start, end)
    spans: list[tuple[int, int]] = []
    index = 0
    while index < len(sentences):
        chunk_start = sentences[index][0]
        last = index
        while last + 1 < len(sentences) and sentences[last + 1][1] - chunk_start <= MAX_CHUNK_CHARS:
            last += 1
        spans.append((chunk_start, sentences[last][1]))
        if last + 1 >= len(sentences):
            break
        # Overlap: step back over trailing sentences of this chunk, taking as
        # many as fit in MAX_OVERLAP_CHARS (a MAX — zero overlap is legal when
        # even one trailing sentence exceeds it).
        next_index = last + 1
        overlap_start_index = next_index
        while (
            overlap_start_index - 1 > index
            and sentences[last][1] - sentences[overlap_start_index - 1][0] <= MAX_OVERLAP_CHARS
        ):
            overlap_start_index -= 1
        index = overlap_start_index
    return spans


def chunk_markdown_note(
    document: str,
    note_path: str,
    source_type: str = "vault",
    note_title: str | None = None,
    note_date: str | None = None,
) -> list[Chunk]:
    """Chunk one markdown document into citation-exact, contextualized chunks.

    Deterministic: identical inputs yield identical chunk lists. A
    frontmatter-only note yields zero chunks (its fields remain reachable
    via the structured notes_meta route). ``note_title`` defaults to the
    frontmatter ``title`` then the filename stem; ``note_date`` defaults to
    frontmatter ``date`` then ``created``.
    """
    parsed = parse_note(document)
    title = note_title or _scalar(parsed.frontmatter.get("title"))
    if not title:
        stem = note_path.rsplit("/", 1)[-1]
        title = stem[:-3] if stem.lower().endswith(".md") else stem
    date = note_date or _scalar(parsed.frontmatter.get("date")) or _scalar(
        parsed.frontmatter.get("created")
    )
    line_starts = _line_offsets(document)
    chunks: list[Chunk] = []
    for breadcrumb, section_start, section_end in _sections(
        document, parsed.headings, parsed.body_start_line, line_starts
    ):
        for span_start, span_end in _split_section(document, section_start, section_end):
            text = document[span_start:span_end]
            prefix = build_contextual_prefix(title, breadcrumb, date, parsed.frontmatter)
            chunks.append(
                Chunk(
                    note_path=note_path,
                    source_type=source_type,
                    note_title=title,
                    heading_path=breadcrumb,
                    line_start=_line_of_offset(line_starts, span_start),
                    line_end=_line_of_offset(line_starts, span_end - 1),
                    char_start=span_start,
                    char_end=span_end,
                    text=text,
                    contextualized_text=f"{prefix}\n\n{text}",
                )
            )
    return chunks


def _scalar(value: str | list[str] | None) -> str | None:
    """First scalar of a lenient frontmatter value, or None."""
    if isinstance(value, list):
        return value[0] if value else None
    return value
