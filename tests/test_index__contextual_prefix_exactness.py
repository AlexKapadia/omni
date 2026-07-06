"""Deterministic contextual-prefix tests: EXACT string equality.

The prefix is the zero-LLM-cost contextual-retrieval variant — its format
is a contract (identical inputs must embed identically forever), so these
tests compare whole strings, not fragments.
"""

from engine.index.markdown_heading_aware_chunker import (
    build_contextual_prefix,
    chunk_markdown_note,
)


def test_full_prefix_renders_every_line_in_fixed_order() -> None:
    prefix = build_contextual_prefix(
        note_title="Weekly Sync",
        heading_path="Alpha > Beta",
        note_date="2026-03-02",
        frontmatter={
            "status": "open",  # deliberately out of KEY order in the mapping
            "tags": ["alpha", "beta"],
            "type": "meeting",
            "irrelevant": "never rendered",
        },
    )
    assert prefix == (
        "Note: Weekly Sync\n"
        "Section: Alpha > Beta\n"
        "Date: 2026-03-02\n"
        "Type: meeting\n"
        "Tags: alpha, beta\n"
        "Status: open"
    )


def test_minimal_prefix_is_title_only() -> None:
    assert build_contextual_prefix("Idea", "", None, {}) == "Note: Idea"


def test_empty_values_are_omitted_not_rendered_blank() -> None:
    prefix = build_contextual_prefix(
        "N", "", None, {"tags": [], "status": "", "type": "note"}
    )
    assert prefix == "Note: N\nType: note"


def test_chunk_contextualized_text_is_prefix_newline_newline_text() -> None:
    document = (
        "---\n"
        "title: Project Kickoff\n"
        "date: 2026-05-01\n"
        "type: meeting\n"
        "---\n"
        "# Agenda\n"
        "Discuss budget."
    )
    chunks = chunk_markdown_note(document, note_path="kickoff.md")
    assert len(chunks) == 1
    assert chunks[0].contextualized_text == (
        "Note: Project Kickoff\n"
        "Section: Agenda\n"
        "Date: 2026-05-01\n"
        "Type: meeting"
        "\n\n"
        "Discuss budget."
    )


def test_title_falls_back_to_frontmatter_then_filename_stem() -> None:
    with_fm = chunk_markdown_note("---\ntitle: Real Title\n---\nbody", note_path="a/b.md")
    assert with_fm[0].note_title == "Real Title"
    from_stem = chunk_markdown_note("body", note_path="people/Priya Sharma.md")
    assert from_stem[0].note_title == "Priya Sharma"


def test_date_falls_back_to_created_when_date_absent() -> None:
    chunks = chunk_markdown_note("---\ncreated: 2025-12-31\n---\nbody", note_path="n.md")
    assert "Date: 2025-12-31" in chunks[0].contextualized_text


def test_prefix_is_deterministic_for_identical_inputs() -> None:
    frontmatter: dict[str, str | list[str]] = {"tags": ["x"], "type": "note"}
    outputs = {
        build_contextual_prefix("T", "A > B", "2026-01-01", frontmatter) for _ in range(10)
    }
    assert len(outputs) == 1
