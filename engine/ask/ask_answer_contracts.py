"""Typed contracts the ask layer returns and emits (and their WS payloads).

Purpose: the single definition of what Ask-Omni hands back
(:class:`AskAnswer` with exact ``[n]`` citations and the latency
breakdown) and what the live spotter emits (:class:`LiveAnswerHit`), plus
the payload shapers the deferred server wiring serialises verbatim.
Pipeline position: produced by ``ask_omni_answer_service`` and
``live_answers_spotter``; consumed by the WS wiring and (as JSON) by the
React frontend, which parses these shapes fail-closed.

Exactness invariants:
- ``AskLatencyBreakdown.total_ms`` is retrieval + synthesis BY
  CONSTRUCTION (a property, not a third measurement) — the arithmetic is
  exact to the unit, tested (§3.11 zero numerical errors).
- Citation fields are copied verbatim from ``RetrievedChunk`` provenance;
  the UI renders ``note_path . L{start}-{end}`` from them (the M3 §Cite
  contract; the real string uses the middle-dot/en-dash characters).
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class AskCitation:
    """One cited source: marker number ``n`` plus exact file+line target."""

    n: int  # the inline [n] marker in answer_md; 1-based chunk order
    note_path: str
    line_start: int  # 1-based inclusive (chunk provenance, verbatim)
    line_end: int  # 1-based inclusive
    heading_path: str
    quote: str  # the cited chunk's text (deterministically truncated)


@dataclass(frozen=True)
class AskLatencyBreakdown:
    """Measured retrieval + synthesis spans; total derived, never measured.

    Speed is a showcase feature (session mandate): the UI renders these
    numbers verbatim under every answer.
    """

    retrieval_ms: int
    synthesis_ms: int

    @property
    def total_ms(self) -> int:
        """Exact by construction: retrieval + synthesis, to the unit."""
        return self.retrieval_ms + self.synthesis_ms


@dataclass(frozen=True)
class AskAnswer:
    """One grounded answer: markdown with [n] markers + exact citations."""

    headline: str  # short display headline (2-6 words)
    answer_md: str  # answer text; [n] markers reference `citations` by n
    no_answer: bool  # True = honest "not in your notes" (no synthesis ran,
    # or the model reported the context does not contain the answer)
    citations: tuple[AskCitation, ...]
    latency: AskLatencyBreakdown


@dataclass(frozen=True)
class LiveAnswerSource:
    """One live-tier hit: exact source provenance, no synthesized prose."""

    note_path: str
    line_start: int  # 1-based inclusive
    line_end: int  # 1-based inclusive
    heading_path: str
    snippet: str  # the chunk text (deterministically truncated)
    score: float  # RRF score, or 0.0 for exact structured-SQL routes


@dataclass(frozen=True)
class LiveAnswerHit:
    """A spotted question plus its top retrieved sources (live tier)."""

    question: str
    asked_by: str  # 'me' | 'them' | 'unknown' (model output, normalised)
    spotted_to_hit_ms: int  # question detection -> hits ready (<2 s budget)
    sources: tuple[LiveAnswerSource, ...]


def ask_answer_to_payload(answer: AskAnswer) -> dict[str, object]:
    """The pinned ``ask.answer`` reply payload (see package docstring)."""
    return {
        "headline": answer.headline,
        "answer_md": answer.answer_md,
        "no_answer": answer.no_answer,
        "citations": [
            {
                "n": citation.n,
                "note_path": citation.note_path,
                "line_start": citation.line_start,
                "line_end": citation.line_end,
                "heading_path": citation.heading_path,
                "quote": citation.quote,
            }
            for citation in answer.citations
        ],
        "latency": {
            "retrieval_ms": answer.latency.retrieval_ms,
            "synthesis_ms": answer.latency.synthesis_ms,
            "total_ms": answer.latency.total_ms,
        },
    }


def answer_hit_to_payload(hit: LiveAnswerHit) -> dict[str, object]:
    """The pinned ``answers.hit`` event payload (see package docstring)."""
    return {
        "question": hit.question,
        "asked_by": hit.asked_by,
        "spotted_to_hit_ms": hit.spotted_to_hit_ms,
        "hits": [
            {
                "note_path": source.note_path,
                "line_start": source.line_start,
                "line_end": source.line_end,
                "heading_path": source.heading_path,
                "snippet": source.snippet,
                "score": source.score,
            }
            for source in hit.sources
        ],
    }
