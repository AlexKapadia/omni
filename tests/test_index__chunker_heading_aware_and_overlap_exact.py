"""Chunker tests: heading nesting, splitting, boundary-exact overlap, determinism.

All fixtures are synthetic. The invariant enforced throughout:
``chunk.text == document[chunk.char_start:chunk.char_end]`` — the citation
contract depends on it.
"""

from itertools import pairwise

from engine.index.markdown_heading_aware_chunker import (
    MAX_CHUNK_CHARS,
    MAX_CHUNK_TOKENS,
    MAX_OVERLAP_CHARS,
    Chunk,
    chunk_markdown_note,
    estimate_tokens,
)

_NESTED_DOC = """---
title: Weekly Sync
date: 2026-03-02
---
Intro paragraph.

# Alpha
Alpha text.

## Beta
Beta text.

### Gamma
Gamma text.

## Delta
Delta text.

# Epsilon
Epsilon text.
"""


def _assert_slice_invariant(document: str, chunks: list[Chunk]) -> None:
    for chunk in chunks:
        assert chunk.text == document[chunk.char_start : chunk.char_end]


def test_heading_nesting_builds_breadcrumbs_and_sibling_resets() -> None:
    chunks = chunk_markdown_note(_NESTED_DOC, note_path="sync.md")
    by_text = {c.text: c.heading_path for c in chunks}
    assert by_text["Intro paragraph."] == ""  # preamble: outside any heading
    assert by_text["Alpha text."] == "Alpha"
    assert by_text["Beta text."] == "Alpha > Beta"
    assert by_text["Gamma text."] == "Alpha > Beta > Gamma"
    assert by_text["Delta text."] == "Alpha > Delta"  # H3 popped by sibling H2
    assert by_text["Epsilon text."] == "Epsilon"  # full reset at H1
    _assert_slice_invariant(_NESTED_DOC, chunks)


def test_no_headings_yields_single_chunk_with_empty_breadcrumb() -> None:
    document = "Just a plain note.\nSecond line."
    chunks = chunk_markdown_note(document, note_path="plain.md")
    assert len(chunks) == 1
    assert chunks[0].heading_path == ""
    assert chunks[0].line_start == 1
    assert chunks[0].line_end == 2
    _assert_slice_invariant(document, chunks)


def test_frontmatter_only_note_yields_zero_chunks() -> None:
    document = "---\ntitle: Contacts\ntags:\n  - people\n---\n"
    assert chunk_markdown_note(document, note_path="contacts.md") == []


def test_empty_and_whitespace_documents_yield_zero_chunks() -> None:
    assert chunk_markdown_note("", note_path="empty.md") == []
    assert chunk_markdown_note("   \n\n  \n", note_path="blank.md") == []


def test_heading_with_empty_section_produces_no_chunk() -> None:
    document = "# Empty\n# Full\ncontent here"
    chunks = chunk_markdown_note(document, note_path="n.md")
    assert [c.heading_path for c in chunks] == ["Full"]


def test_section_at_exactly_max_chars_is_one_chunk_and_one_over_splits() -> None:
    """Boundary-exact: on / just-under the cap = 1 chunk; just-over splits."""
    # Sentences of exactly 100 chars ("x"*98 + ". ") pack the cap exactly.
    sentence = "x" * 98 + ". "
    at_cap = sentence * (MAX_CHUNK_CHARS // 100)
    assert len(at_cap) == MAX_CHUNK_CHARS
    chunks = chunk_markdown_note(at_cap, note_path="cap.md")
    # Trailing whitespace is trimmed, so the single chunk is 1599 chars.
    assert len(chunks) == 1
    over_cap = at_cap + "y" * 2  # 1602 chars, forces a split
    over_chunks = chunk_markdown_note(over_cap, note_path="over.md")
    assert len(over_chunks) > 1
    _assert_slice_invariant(over_cap, over_chunks)


def test_split_chunks_respect_token_cap_and_overlap_maximum_exactly() -> None:
    """Every chunk ≤ 400 heuristic tokens; every overlap ≤ 80 tokens (320
    chars) — measured exactly from the char spans, not approximated."""
    sentence = "s" * 158 + ". "  # 160-char sentences: overlap packs to exactly 320
    document = sentence * 40  # 6400 chars, must split
    chunks = chunk_markdown_note(document, note_path="long.md")
    assert len(chunks) > 1
    for chunk in chunks:
        assert estimate_tokens(chunk.text) <= MAX_CHUNK_TOKENS
        assert len(chunk.text) <= MAX_CHUNK_CHARS
    overlaps = [
        chunks[i].char_end - chunks[i + 1].char_start
        for i in range(len(chunks) - 1)
    ]
    assert all(0 <= overlap <= MAX_OVERLAP_CHARS for overlap in overlaps)
    # 160-char sentences: two trailing sentences = exactly 320 chars = the max.
    assert max(overlaps) == MAX_OVERLAP_CHARS
    _assert_slice_invariant(document, chunks)


def test_overlap_just_over_the_maximum_is_excluded() -> None:
    """161-char sentences: one fits (161 ≤ 320), two (322) would exceed —
    the boundary case must resolve to the smaller overlap."""
    sentence = "t" * 159 + ". "
    document = sentence * 40
    chunks = chunk_markdown_note(document, note_path="edge.md")
    overlaps = [
        chunks[i].char_end - chunks[i + 1].char_start for i in range(len(chunks) - 1)
    ]
    assert all(overlap <= MAX_OVERLAP_CHARS for overlap in overlaps)
    assert max(overlaps) == 161  # exactly one trailing sentence, never two


def test_unsplittable_wall_of_text_is_hard_split_without_overlap() -> None:
    document = "z" * 5000  # no sentence boundaries at all
    chunks = chunk_markdown_note(document, note_path="wall.md")
    assert [len(c.text) for c in chunks] == [1600, 1600, 1600, 200]
    for earlier, later in pairwise(chunks):
        assert later.char_start == earlier.char_end  # contiguous, zero overlap
    _assert_slice_invariant(document, chunks)


def test_unicode_content_keeps_exact_slices_and_line_numbers() -> None:
    # Deliberately mixed scripts (Cyrillic is the point, not a typo).
    document = "# Café ☕\nПривет мир. 你好世界。\némoji 🙂 line."  # noqa: RUF001
    chunks = chunk_markdown_note(document, note_path="unicode.md")
    assert len(chunks) == 1
    assert chunks[0].heading_path == "Café ☕"
    assert chunks[0].line_start == 2
    assert chunks[0].line_end == 3
    _assert_slice_invariant(document, chunks)


def test_chunking_is_deterministic_across_repeated_runs() -> None:
    runs = [chunk_markdown_note(_NESTED_DOC, note_path="sync.md") for _ in range(5)]
    assert all(run == runs[0] for run in runs)


def test_line_numbers_are_one_based_and_inclusive() -> None:
    document = "line one\n\n# Head\nline four\nline five\n"
    chunks = chunk_markdown_note(document, note_path="lines.md")
    preamble = next(c for c in chunks if c.heading_path == "")
    section = next(c for c in chunks if c.heading_path == "Head")
    assert (preamble.line_start, preamble.line_end) == (1, 1)
    assert (section.line_start, section.line_end) == (4, 5)


def test_estimate_tokens_heuristic_is_ceil_chars_over_four() -> None:
    assert estimate_tokens("") == 0
    assert estimate_tokens("abcd") == 1
    assert estimate_tokens("abcde") == 2  # just over: rounds UP
    assert estimate_tokens("x" * 1600) == 400  # the cap, exactly
