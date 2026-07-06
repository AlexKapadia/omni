"""Retrieval result types and the exact citation contract.

Purpose: the single definition of what every retrieval path (hybrid,
structured, graph expansion) returns, and of the citation string the UI
renders. One shape everywhere means the Ask-Omni service and the UI never
special-case a retrieval source.
Pipeline position: produced by ``hybrid_rrf_retriever``,
``structured_sql_lookup_executor``, and ``structural_graph_expander``;
consumed by M3's Ask-Omni service and ultimately the React frontend.

Citation contract (binding, tested): ``note_path · L<start>-<end>`` with a
1-based inclusive line range and an EN DASH between the line numbers —
exactly what the UI already renders. The cited span must contain the
chunk's exact source text (fidelity invariant enforced by the chunker).
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class RetrievedChunk:
    """One retrieved chunk plus provenance — everything needed to cite it."""

    chunk_id: int
    note_path: str
    source_type: str  # 'vault' | 'transcript'
    note_title: str
    heading_path: str
    line_start: int  # 1-based inclusive
    line_end: int  # 1-based inclusive
    text: str
    contextualized_text: str
    score: float  # RRF score, rerank score, or 0.0 for exact-SQL routes
    retrieval_source: str  # 'hybrid_rrf' | 'graph_expansion' | 'structured_*' | 'reranked'

    @property
    def citation(self) -> str:
        """The exact citation string the UI renders (en-dash line range)."""
        return format_citation(self.note_path, self.line_start, self.line_end)


def format_citation(note_path: str, line_start: int, line_end: int) -> str:
    """Format the binding citation string (middle dot, en dash — tested)."""
    # The en dash is the contract, not a typo (UI renders it verbatim).
    return f"{note_path} · L{line_start}–{line_end}"  # noqa: RUF001
