"""Latency arithmetic and WS payload shapes — exact to the unit (§3.11).

Claims under test: retrieval/synthesis spans come from the injected clock
with exact rounding; total_ms is retrieval + synthesis BY CONSTRUCTION;
the pinned ``ask.answer`` / ``answers.hit`` payload dicts match the
documented wiring contract field-for-field.
"""

import json
from pathlib import Path

import aiosqlite

from engine.ask.ask_answer_contracts import (
    AskAnswer,
    AskCitation,
    AskLatencyBreakdown,
    LiveAnswerHit,
    LiveAnswerSource,
    answer_hit_to_payload,
    ask_answer_to_payload,
)
from engine.ask.ask_omni_answer_service import AskOmniAnswerService
from engine.index.retrieved_chunk_types import RetrievedChunk
from engine.router.completion_contract import (
    ChatMessage,
    Provider,
    ProviderCompletion,
    RoutedCompletion,
    ToolSpec,
)
from engine.storage import apply_migrations, open_sqlite_connection


class ScriptedClock:
    """Returns scripted instants; a sequence overrun is a test bug."""

    def __init__(self, instants: list[float]) -> None:
        self._instants = list(instants)

    def __call__(self) -> float:
        assert self._instants, "clock called more times than the test scripted"
        return self._instants.pop(0)


class FakeRouter:
    def __init__(self, reply_text: str) -> None:
        self._reply_text = reply_text
        self.calls = 0

    async def route(
        self,
        task_type: str,
        system_frame: str,
        messages: tuple[ChatMessage, ...],
        *,
        tools: tuple[ToolSpec, ...] = (),
        json_schema: dict[str, object] | None = None,
        max_tokens: int = 4096,
    ) -> RoutedCompletion:
        self.calls += 1
        completion = ProviderCompletion(
            text=self._reply_text,
            provider=Provider.GEMINI,
            model="gemini-2.5-flash",
            prompt_tokens=1,
            completion_tokens=1,
        )
        return RoutedCompletion(
            completion=completion,
            provider=Provider.GEMINI,
            model="gemini-2.5-flash",
            latency_ms=1,
        )


def make_chunk() -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=1,
        note_path="notes/a.md",
        source_type="vault",
        note_title="A",
        heading_path="H",
        line_start=3,
        line_end=5,
        text="The fact.",
        contextualized_text="A > H\nThe fact.",
        score=0.05,
        retrieval_source="hybrid_rrf",
    )


class FakeRetriever:
    def __init__(self, results: list[RetrievedChunk]) -> None:
        self._results = results

    async def retrieve(
        self,
        query: str,
        tier: str = "live",
        top_n: int = 8,
        enable_graph_expansion: bool = True,
    ) -> list[RetrievedChunk]:
        return list(self._results)


async def _empty_db(tmp_db_path: Path, real_migrations_dir: Path) -> aiosqlite.Connection:
    await apply_migrations(tmp_db_path, real_migrations_dir)
    return await open_sqlite_connection(tmp_db_path)


async def test_answer_latency_spans_are_measured_exactly(
    tmp_db_path: Path, real_migrations_dir: Path
) -> None:
    connection = await _empty_db(tmp_db_path, real_migrations_dir)
    try:
        # Clock calls: start, end-of-retrieval, start-of-synthesis, end.
        clock = ScriptedClock([10.0, 10.1504, 10.1504, 10.9504])
        reply = json.dumps({"headline": "H", "answer": "The fact [1]."})
        service = AskOmniAnswerService(
            connection, FakeRetriever([make_chunk()]), FakeRouter(reply), clock=clock
        )
        answer = await service.answer("fact?")
        assert answer.latency.retrieval_ms == 150  # round(0.1504*1000) exact
        assert answer.latency.synthesis_ms == 800
        assert answer.latency.total_ms == 950  # sum, exact to the unit
    finally:
        await connection.close()


async def test_no_answer_path_has_zero_synthesis_span(
    tmp_db_path: Path, real_migrations_dir: Path
) -> None:
    connection = await _empty_db(tmp_db_path, real_migrations_dir)
    try:
        clock = ScriptedClock([0.0, 0.075])  # start, end-of-retrieval only
        service = AskOmniAnswerService(
            connection, FakeRetriever([]), FakeRouter("unused"), clock=clock
        )
        answer = await service.answer("missing thing?")
        assert answer.latency.retrieval_ms == 75
        assert answer.latency.synthesis_ms == 0
        assert answer.latency.total_ms == 75
    finally:
        await connection.close()


def test_total_ms_is_the_sum_by_construction() -> None:
    for retrieval, synthesis in ((0, 0), (1, 0), (149, 851), (12_345, 67_890)):
        breakdown = AskLatencyBreakdown(retrieval_ms=retrieval, synthesis_ms=synthesis)
        assert breakdown.total_ms == retrieval + synthesis


def test_ask_answer_payload_matches_the_pinned_wiring_contract() -> None:
    answer = AskAnswer(
        headline="March pricing",
        answer_md="Held at $18/seat [1].",
        no_answer=False,
        citations=(
            AskCitation(
                n=1,
                note_path="meetings/2026-03-12.md",
                line_start=7,
                line_end=9,
                heading_path="Decisions",
                quote="Hold the per-seat price at $18.",
            ),
        ),
        latency=AskLatencyBreakdown(retrieval_ms=12, synthesis_ms=840),
    )
    assert ask_answer_to_payload(answer) == {
        "headline": "March pricing",
        "answer_md": "Held at $18/seat [1].",
        "no_answer": False,
        "citations": [
            {
                "n": 1,
                "note_path": "meetings/2026-03-12.md",
                "line_start": 7,
                "line_end": 9,
                "heading_path": "Decisions",
                "quote": "Hold the per-seat price at $18.",
            }
        ],
        "latency": {"retrieval_ms": 12, "synthesis_ms": 840, "total_ms": 852},
    }


def test_answers_hit_payload_matches_the_pinned_wiring_contract() -> None:
    hit = LiveAnswerHit(
        question="What did we quote them last year?",
        asked_by="them",
        spotted_to_hit_ms=740,
        sources=(
            LiveAnswerSource(
                note_path="clients/acme.md",
                line_start=42,
                line_end=58,
                heading_path="Renewal",
                snippet="Quoted $71,500 multi-tenant.",
                score=0.031,
            ),
        ),
    )
    assert answer_hit_to_payload(hit) == {
        "question": "What did we quote them last year?",
        "asked_by": "them",
        "spotted_to_hit_ms": 740,
        "hits": [
            {
                "note_path": "clients/acme.md",
                "line_start": 42,
                "line_end": 58,
                "heading_path": "Renewal",
                "snippet": "Quoted $71,500 multi-tenant.",
                "score": 0.031,
            }
        ],
    }
