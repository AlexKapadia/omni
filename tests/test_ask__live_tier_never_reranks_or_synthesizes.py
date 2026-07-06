"""Live-tier discipline: the spotter retrieves live-only and never synthesises.

Claims under test: every spotter retrieval runs tier='live' with graph
expansion OFF and top 5 (route + hybrid RRF only — the <2 s budget); the
ONLY router task the spotter ever requests is ``live_extraction`` (never
``ask_synthesis``); emitted hits map chunk provenance exactly and carry a
``spotted_to_hit_ms`` measured from the injected clock to the unit; weak
(below-floor) retrieval emits nothing.
"""

import json
from pathlib import Path

import aiosqlite

from engine.ask.ask_answer_contracts import LiveAnswerHit
from engine.ask.live_answers_spotter import LiveAnswersSpotter
from engine.ask.structured_first_retrieval import MINIMUM_HYBRID_RRF_SCORE
from engine.index.retrieved_chunk_types import RetrievedChunk
from engine.router.completion_contract import (
    ChatMessage,
    Provider,
    ProviderCompletion,
    RoutedCompletion,
    ToolSpec,
)
from engine.storage import apply_migrations, open_sqlite_connection

QUESTION = "What did we agree on pricing in the Acme renewal?"


class ScriptedClock:
    def __init__(self, instants: list[float]) -> None:
        self._instants = list(instants)

    def __call__(self) -> float:
        assert self._instants, "clock called more times than the test scripted"
        return self._instants.pop(0)


class FakeRouter:
    def __init__(self) -> None:
        self.task_types: list[str] = []

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
        self.task_types.append(task_type)
        completion = ProviderCompletion(
            text=json.dumps({"questions": [{"text": QUESTION, "asked_by": "them"}]}),
            provider=Provider.GROQ,
            model="llama-3.3-70b-versatile",
            prompt_tokens=1,
            completion_tokens=1,
        )
        return RoutedCompletion(
            completion=completion,
            provider=Provider.GROQ,
            model="llama-3.3-70b-versatile",
            latency_ms=1,
        )


def make_chunk(score: float) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=7,
        note_path="meetings/2026-03-12-acme.md",
        source_type="vault",
        note_title="Acme pricing",
        heading_path="Decisions",
        line_start=11,
        line_end=14,
        text="Hold the per-seat price at $18 through Q3.",
        contextualized_text="Acme pricing > Decisions\nHold the per-seat price at $18.",
        score=score,
        retrieval_source="hybrid_rrf",
    )


class RecordingRetriever:
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


async def _run_one_spot(
    tmp_db_path: Path,
    real_migrations_dir: Path,
    retriever: RecordingRetriever,
    clock: ScriptedClock,
) -> tuple[FakeRouter, list[LiveAnswerHit], aiosqlite.Connection]:
    await apply_migrations(tmp_db_path, real_migrations_dir)
    connection = await open_sqlite_connection(tmp_db_path)
    router = FakeRouter()
    hits: list[LiveAnswerHit] = []

    async def emit(hit: LiveAnswerHit) -> None:
        hits.append(hit)

    spotter = LiveAnswersSpotter(
        connection, retriever, router, emit, cadence_seconds=1.0, clock=clock
    )
    await spotter.on_final_segment("them", QUESTION)
    return router, hits, connection


async def test_spotter_retrieves_live_tier_only_and_never_asks_for_synthesis(
    tmp_db_path: Path, real_migrations_dir: Path
) -> None:
    # init, cadence check, window stamp, spotted_at, hit-ready.
    clock = ScriptedClock([0.0, 30.0, 30.0, 30.05, 30.79])
    retriever = RecordingRetriever([make_chunk(score=0.05)])
    router, hits, connection = await _run_one_spot(
        tmp_db_path, real_migrations_dir, retriever, clock
    )
    try:
        # THE binding tier discipline: live, no graph expansion, top 5.
        assert retriever.calls == [
            {"query": QUESTION, "tier": "live", "top_n": 5, "graph": False}
        ]
        # The spotter's ONLY egress task — synthesis never appears.
        assert router.task_types == ["live_extraction"]
        assert len(hits) == 1
        hit = hits[0]
        assert hit.question == QUESTION
        assert hit.asked_by == "them"
        # Exact from the scripted clock: (30.79 - 30.05) s -> 740 ms.
        assert hit.spotted_to_hit_ms == 740
        source = hit.sources[0]
        assert source.note_path == "meetings/2026-03-12-acme.md"
        assert (source.line_start, source.line_end) == (11, 14)
        assert source.heading_path == "Decisions"
        assert source.snippet == "Hold the per-seat price at $18 through Q3."
        assert source.score == 0.05
    finally:
        await connection.close()


async def test_below_floor_hits_are_weak_and_never_emitted(
    tmp_db_path: Path, real_migrations_dir: Path
) -> None:
    clock = ScriptedClock([0.0, 30.0, 30.0, 30.05])  # no hit-ready instant needed
    retriever = RecordingRetriever([make_chunk(score=MINIMUM_HYBRID_RRF_SCORE - 1e-12)])
    router, hits, connection = await _run_one_spot(
        tmp_db_path, real_migrations_dir, retriever, clock
    )
    try:
        assert router.task_types == ["live_extraction"]  # spotting DID run
        assert len(retriever.calls) == 1  # retrieval DID run
        assert hits == []  # honest: nothing above the floor, nothing emitted
    finally:
        await connection.close()
