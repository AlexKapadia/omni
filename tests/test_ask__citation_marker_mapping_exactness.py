"""Citation-mapping exactness: [n] markers ↔ chunks, never a dangling n.

Claims under test: source numbering IS the chunk order (1-based); markers
the model invents are stripped from the answer; citations exist only for
markers actually present in the final answer text, each quoting exactly
its chunk; quote truncation is boundary-exact.
"""

from engine.ask.citation_marker_mapping import (
    MAX_QUOTE_CHARS,
    build_numbered_context,
    citations_for_answer,
    extract_citation_markers,
    strip_dangling_markers,
    truncate_quote,
)
from engine.index.retrieved_chunk_types import RetrievedChunk


def make_chunk(
    chunk_id: int,
    note_path: str = "notes/a.md",
    text: str = "Budget is $10.",
    heading_path: str = "Budget",
    line_start: int = 4,
    line_end: int = 6,
    score: float = 0.05,
    retrieval_source: str = "hybrid_rrf",
) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=chunk_id,
        note_path=note_path,
        source_type="vault",
        note_title="A",
        heading_path=heading_path,
        line_start=line_start,
        line_end=line_end,
        text=text,
        contextualized_text=f"A > {heading_path}\n{text}",
        score=score,
        retrieval_source=retrieval_source,
    )


def test_numbered_context_is_exact_and_order_defined() -> None:
    chunks = [
        make_chunk(9, note_path="clients/acme.md", text="Seat price $18.", heading_path="Pricing"),
        make_chunk(2, note_path="people/priya.md", text="Phone: 123.", heading_path=""),
    ]
    context = build_numbered_context(chunks)
    # Chunk ORDER defines numbering — chunk ids are irrelevant to markers.
    assert context == (
        "[1] clients/acme.md · L4–6 › Pricing\nSeat price $18."  # noqa: RUF001
        "\n\n[2] people/priya.md · L4–6\nPhone: 123."  # noqa: RUF001
    )


def test_marker_extraction_orders_by_first_appearance_and_dedupes() -> None:
    assert extract_citation_markers("b [2] a [1] again [2] [10]") == [2, 1, 10]
    assert extract_citation_markers("no markers here") == []
    assert extract_citation_markers("[not] [1a] [ 2 ]") == []  # digits only


def test_dangling_markers_are_stripped_without_double_spaces() -> None:
    assert strip_dangling_markers("Price is $18 [1].", 2) == "Price is $18 [1]."
    assert strip_dangling_markers("Price is $18 [3].", 2) == "Price is $18."
    assert strip_dangling_markers("Zero [0] and huge [99] gone [2]", 2) == (
        "Zero and huge gone [2]"
    )
    # Boundary-exact: n == chunk_count survives; n == chunk_count+1 dies.
    assert strip_dangling_markers("[2]", 2) == "[2]"
    assert strip_dangling_markers("[3]", 2) == ""


def test_citations_exist_only_for_markers_present_ascending_by_n() -> None:
    chunks = [
        make_chunk(1, note_path="a.md", text="Fact A."),
        make_chunk(2, note_path="b.md", text="Fact B.", line_start=10, line_end=12),
        make_chunk(3, note_path="c.md", text="Never cited."),
    ]
    citations = citations_for_answer(chunks, "B first [2], then A [1].")
    assert [c.n for c in citations] == [1, 2]  # ascending regardless of order
    assert citations[0].note_path == "a.md"
    assert citations[0].quote == "Fact A."
    assert citations[1].note_path == "b.md"
    assert (citations[1].line_start, citations[1].line_end) == (10, 12)
    # Chunk 3 was provided but never cited: no citation row for it.
    assert all(c.note_path != "c.md" for c in citations)


def test_no_citation_can_ever_point_at_nothing() -> None:
    """The full contract: strip THEN map — every marker resolves to a chunk."""
    chunks = [make_chunk(1), make_chunk(2)]
    for adversarial in ("[1][2][3][4]", "only [7]", "[0] [1]", "[2] [999] tail"):
        answer = strip_dangling_markers(adversarial, len(chunks))
        citations = citations_for_answer(chunks, answer)
        markers_in_answer = set(extract_citation_markers(answer))
        assert markers_in_answer == {c.n for c in citations}
        assert all(1 <= c.n <= len(chunks) for c in citations)


def test_quote_truncation_is_boundary_exact() -> None:
    exactly_at_limit = "x" * MAX_QUOTE_CHARS
    assert truncate_quote(exactly_at_limit) == exactly_at_limit  # on the limit
    over = "x" * (MAX_QUOTE_CHARS + 1)
    truncated = truncate_quote(over)
    assert len(truncated) == MAX_QUOTE_CHARS  # never longer than the limit
    assert truncated.endswith("…")
    assert truncated[:-1] == "x" * (MAX_QUOTE_CHARS - 1)  # verbatim prefix
    assert truncate_quote("  padded  ") == "padded"  # strip is part of the contract
