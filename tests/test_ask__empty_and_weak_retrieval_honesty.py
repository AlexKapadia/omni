"""Fail-honest gate: empty/weak retrieval NEVER reaches a provider.

Claims under test: no chunks (or only below-floor hybrid chunks) means the
exact "I don't have that in your notes." answer with ZERO router calls;
the floor boundary is exact (on / just-over / just-under); graph-expansion
children die with their floored seeds; a model-reported no-answer comes
back canonical with no citations.
"""

import json
from pathlib import Path

import aiosqlite

from engine.ask.ask_omni_answer_service import AskOmniAnswerService
from engine.ask.ask_prompt_frames import NO_ANSWER_TEXT
from engine.ask.structured_first_retrieval import (
    MINIMUM_HYBRID_RRF_SCORE,
    apply_hybrid_score_floor,
)
from engine.index.retrieved_chunk_types import RetrievedChunk
from engine.router.completion_contract import (
    ChatMessage,
    Provider,
    ProviderCompletion,
    RoutedCompletion,
    ToolSpec,
)
from engine.storage import apply_migrations, open_sqlite_connection


def make_chunk(
    chunk_id: int, score: float, retrieval_source: str = "hybrid_rrf"
) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=chunk_id,
        note_path="notes/a.md",
        source_type="vault",
        note_title="A",
        heading_path="H",
        line_start=1,
        line_end=2,
        text="Some fact.",
        contextualized_text="A > H\nSome fact.",
        score=score,
        retrieval_source=retrieval_source,
    )


class FakeRouter:
    """Records every call; returns a fixed schema-shaped synthesis reply."""

    def __init__(self, reply_text: str | None = None) -> None:
        self.calls: list[tuple[str, str, tuple[ChatMessage, ...]]] = []
        self._reply_text = reply_text or json.dumps(
            {"headline": "The fact", "answer": "Some fact [1]."}
        )

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
        self.calls.append((task_type, system_frame, messages))
        completion = ProviderCompletion(
            text=self._reply_text,
            provider=Provider.GEMINI,
            model="gemini-2.5-flash",
            prompt_tokens=10,
            completion_tokens=5,
        )
        return RoutedCompletion(
            completion=completion,
            provider=Provider.GEMINI,
            model="gemini-2.5-flash",
            latency_ms=100,
        )


class FakeRetriever:
    def __init__(self, results: list[RetrievedChunk]) -> None:
        self._results = results
        self.calls: list[dict[str, object]] = []

    async def retrieve(
        self,
        query: str,
        tier: str = "live",
        top_n: int = 8,
        enable_graph_expansion: bool = True,
    ) -> list[RetrievedChunk]:
        self.calls.append(
            {"query": query, "tier": tier, "top_n": top_n, "graph": enable_graph_expansion}
        )
        return list(self._results)


async def _empty_db(tmp_db_path: Path, real_migrations_dir: Path) -> aiosqlite.Connection:
    """A real migrated DB with no entities/notes — every query routes hybrid."""
    await apply_migrations(tmp_db_path, real_migrations_dir)
    return await open_sqlite_connection(tmp_db_path)


async def test_empty_retrieval_answers_honestly_with_zero_router_calls(
    tmp_db_path: Path, real_migrations_dir: Path
) -> None:
    connection = await _empty_db(tmp_db_path, real_migrations_dir)
    try:
        router = FakeRouter()
        service = AskOmniAnswerService(connection, FakeRetriever([]), router)
        answer = await service.answer("what did we agree on the koi pond aerator?")
        assert answer.no_answer is True
        assert answer.answer_md == NO_ANSWER_TEXT
        assert answer.citations == ()
        assert answer.latency.synthesis_ms == 0  # no synthesis span existed
        assert router.calls == []  # THE invariant: zero provider calls
    finally:
        await connection.close()


async def test_below_floor_hybrid_results_are_weak_and_never_synthesised(
    tmp_db_path: Path, real_migrations_dir: Path
) -> None:
    connection = await _empty_db(tmp_db_path, real_migrations_dir)
    try:
        router = FakeRouter()
        just_under = MINIMUM_HYBRID_RRF_SCORE - 1e-12
        retriever = FakeRetriever([make_chunk(1, just_under)])
        service = AskOmniAnswerService(connection, retriever, router)
        answer = await service.answer("anything")
        assert answer.no_answer is True
        assert router.calls == []
    finally:
        await connection.close()


async def test_floor_boundary_is_exact_on_and_over_synthesise(
    tmp_db_path: Path, real_migrations_dir: Path
) -> None:
    connection = await _empty_db(tmp_db_path, real_migrations_dir)
    try:
        for score in (MINIMUM_HYBRID_RRF_SCORE, MINIMUM_HYBRID_RRF_SCORE + 1e-12):
            router = FakeRouter()
            service = AskOmniAnswerService(
                connection, FakeRetriever([make_chunk(1, score)]), router
            )
            answer = await service.answer("anything")
            assert len(router.calls) == 1  # on/over the floor: synthesis runs
            assert answer.no_answer is False
    finally:
        await connection.close()


async def test_graph_expansion_children_die_with_their_floored_seeds(
    tmp_db_path: Path, real_migrations_dir: Path
) -> None:
    connection = await _empty_db(tmp_db_path, real_migrations_dir)
    try:
        router = FakeRouter()
        weak_seed = make_chunk(1, MINIMUM_HYBRID_RRF_SCORE - 1e-12)
        expansion = make_chunk(2, 0.0, retrieval_source="graph_expansion")
        service = AskOmniAnswerService(
            connection, FakeRetriever([weak_seed, expansion]), router
        )
        answer = await service.answer("anything")
        # Expansion chunks are children of the seeds: no seed, no context.
        assert answer.no_answer is True
        assert router.calls == []
    finally:
        await connection.close()


def test_floor_filter_unit_boundaries_and_structured_passthrough() -> None:
    on = make_chunk(1, MINIMUM_HYBRID_RRF_SCORE)
    under = make_chunk(2, MINIMUM_HYBRID_RRF_SCORE - 1e-12)
    over = make_chunk(3, MINIMUM_HYBRID_RRF_SCORE + 1e-12)
    structured = make_chunk(4, 0.0, retrieval_source="structured_entity")
    kept = apply_hybrid_score_floor([on, under, over])
    assert [c.chunk_id for c in kept] == [1, 3]  # order preserved, under dropped
    # Structured chunks (exact SQL, score 0.0) are never floor-filtered.
    assert apply_hybrid_score_floor([structured]) == [structured]
    # Expansion survives while at least one hybrid seed does.
    expansion = make_chunk(5, 0.0, retrieval_source="graph_expansion")
    assert [c.chunk_id for c in apply_hybrid_score_floor([on, expansion])] == [1, 5]


async def test_model_reported_no_answer_comes_back_canonical_without_citations(
    tmp_db_path: Path, real_migrations_dir: Path
) -> None:
    connection = await _empty_db(tmp_db_path, real_migrations_dir)
    try:
        reply = json.dumps({"headline": "Nothing", "answer": NO_ANSWER_TEXT})
        router = FakeRouter(reply_text=reply)
        service = AskOmniAnswerService(
            connection, FakeRetriever([make_chunk(1, 0.05)]), router
        )
        answer = await service.answer("what colour is the CFO's parachute?")
        assert len(router.calls) == 1  # synthesis DID run (context existed)
        assert answer.no_answer is True
        assert answer.answer_md == NO_ANSWER_TEXT
        assert answer.citations == ()
    finally:
        await connection.close()
