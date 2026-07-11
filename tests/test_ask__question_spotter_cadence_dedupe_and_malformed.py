"""Live question spotter: cadence gating, rolling dedupe, malformed tolerance.

Claims under test: no spotting call happens before ~20 s of new final text
has accumulated; the buffered window reaches the model verbatim as DATA;
the same question (case/punctuation aside) hits once until it rolls out of
the dedupe window; malformed spotter output and router failure are
tolerated silently (never a crash, never an invented hit).
"""

import json
from pathlib import Path

import aiosqlite

from engine.ask.ask_answer_contracts import LiveAnswerHit
from engine.ask.ask_prompt_frames import QUESTION_SPOTTER_SYSTEM_FRAME
from engine.ask.live_answers_spotter import (
    LiveAnswersSpotter,
    normalise_question,
    parse_spotted_questions,
)
from engine.index.retrieved_chunk_types import RetrievedChunk
from engine.router.completion_contract import (
    ChatMessage,
    Provider,
    ProviderCompletion,
    RoutedCompletion,
    ToolSpec,
)
from engine.router.router_errors import RouterUnavailableError
from engine.storage import apply_migrations, open_sqlite_connection


class SteppingClock:
    """Monotonic fake advanced explicitly by the test."""

    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


class FakeRouter:
    """Returns queued reply texts (or raises queued errors) in order."""

    def __init__(self, replies: list[str | Exception]) -> None:
        self._replies = list(replies)
        self.calls: list[tuple[str, str, str]] = []  # (task, frame, data)

    async def route(
        self,
        task_type: str,
        system_frame: str,
        messages: tuple[ChatMessage, ...],
        *,
        tools: tuple[ToolSpec, ...] = (),
        json_schema: dict[str, object] | None = None,
        max_tokens: int = 4096,
        preferred_model: str | None = None,
        preferred_provider: str | None = None,
    ) -> RoutedCompletion:
        self.calls.append((task_type, system_frame, messages[0].content))
        reply = self._replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        completion = ProviderCompletion(
            text=reply,
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


def hit_chunk() -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=1,
        note_path="clients/acme.md",
        source_type="vault",
        note_title="Acme",
        heading_path="Pricing",
        line_start=3,
        line_end=4,
        text="Seat price held at $18 through Q3.",
        contextualized_text="Acme > Pricing\nSeat price held at $18 through Q3.",
        score=0.05,
        retrieval_source="hybrid_rrf",
    )


class FakeRetriever:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    async def retrieve(
        self,
        query: str,
        tier: str = "live",
        top_n: int = 8,
        enable_graph_expansion: bool = True,
    ) -> list[RetrievedChunk]:
        self.calls.append({"query": query, "tier": tier})
        return [hit_chunk()]


def spotted(questions: list[tuple[str, str]]) -> str:
    return json.dumps(
        {"questions": [{"text": text, "asked_by": by} for text, by in questions]}
    )


async def _empty_db(tmp_db_path: Path, real_migrations_dir: Path) -> aiosqlite.Connection:
    await apply_migrations(tmp_db_path, real_migrations_dir)
    return await open_sqlite_connection(tmp_db_path)


def _spotter(
    connection: aiosqlite.Connection,
    router: FakeRouter,
    retriever: FakeRetriever,
    hits: list[LiveAnswerHit],
    clock: SteppingClock,
    cadence_seconds: float = 20.0,
    dedupe_capacity: int = 50,
) -> LiveAnswersSpotter:
    async def emit(hit: LiveAnswerHit) -> None:
        hits.append(hit)

    return LiveAnswersSpotter(
        connection,
        retriever,
        router,
        emit,
        cadence_seconds=cadence_seconds,
        dedupe_capacity=dedupe_capacity,
        clock=clock,
    )


async def test_cadence_gates_spotting_and_the_window_reaches_the_model_verbatim(
    tmp_db_path: Path, real_migrations_dir: Path
) -> None:
    connection = await _empty_db(tmp_db_path, real_migrations_dir)
    try:
        clock = SteppingClock()
        router = FakeRouter([spotted([("What did we agree on price?", "them")])])
        retriever = FakeRetriever()
        hits: list[LiveAnswerHit] = []
        spotter = _spotter(connection, router, retriever, hits, clock, cadence_seconds=20.0)
        clock.now = 5.0
        await spotter.on_final_segment("them", "So about the contract.")
        assert router.calls == []  # before the cadence: buffered, not spotted
        clock.now = 19.999
        await spotter.on_final_segment("me", "Sure, go ahead.")
        assert router.calls == []  # boundary-exact: just-under does not fire
        clock.now = 20.0
        await spotter.on_final_segment("them", "What did we agree on price?")
        assert len(router.calls) == 1  # on the boundary: fires
        task_type, frame, data = router.calls[0]
        assert task_type == "live_extraction"
        assert frame == QUESTION_SPOTTER_SYSTEM_FRAME  # constant frame only
        # Whole window, labelled and verbatim, in the DATA channel.
        assert data == (
            "Them: So about the contract.\n"
            "Me: Sure, go ahead.\n"
            "Them: What did we agree on price?"
        )
        assert len(hits) == 1
        assert hits[0].question == "What did we agree on price?"
        assert hits[0].asked_by == "them"
    finally:
        await connection.close()


async def test_repeated_questions_hit_once_until_they_roll_out(
    tmp_db_path: Path, real_migrations_dir: Path
) -> None:
    connection = await _empty_db(tmp_db_path, real_migrations_dir)
    try:
        clock = SteppingClock()
        q1, q2 = "What is the March price?", "Who owns the security review?"
        router = FakeRouter(
            [
                spotted([(q1, "them")]),
                # Same question, different case/punctuation: must dedupe.
                spotted([("what is the MARCH price??", "them"), (q2, "me")]),
                spotted([(q1, "them")]),  # q1 rolled out (capacity 1): re-hits
            ]
        )
        retriever = FakeRetriever()
        hits: list[LiveAnswerHit] = []
        spotter = _spotter(
            connection, router, retriever, hits, clock, cadence_seconds=1.0, dedupe_capacity=1
        )
        for text in ("a?", "b?", "c?"):
            clock.now += 2.0
            await spotter.on_final_segment("them", text)
        assert [hit.question for hit in hits] == [q1, q2, q1]
    finally:
        await connection.close()


async def test_malformed_spotter_output_and_router_failure_are_tolerated(
    tmp_db_path: Path, real_migrations_dir: Path
) -> None:
    connection = await _empty_db(tmp_db_path, real_migrations_dir)
    try:
        clock = SteppingClock()
        router = FakeRouter(
            [
                "not json at all {",
                json.dumps({"questions": "not a list"}),
                json.dumps({"questions": [{"asked_by": "them"}, {"text": "   "}, 7]}),
                RouterUnavailableError("live_extraction", ()),
            ]
        )
        retriever = FakeRetriever()
        hits: list[LiveAnswerHit] = []
        spotter = _spotter(connection, router, retriever, hits, clock, cadence_seconds=1.0)
        for text in ("a?", "b?", "c?", "d?"):
            clock.now += 2.0
            await spotter.on_final_segment("them", text)  # must never raise
        assert hits == []
        assert retriever.calls == []  # nothing parseable ever reached retrieval
        assert len(router.calls) == 4
    finally:
        await connection.close()


async def test_blank_segments_are_ignored_and_never_fill_the_window(
    tmp_db_path: Path, real_migrations_dir: Path
) -> None:
    connection = await _empty_db(tmp_db_path, real_migrations_dir)
    try:
        clock = SteppingClock()
        router = FakeRouter([])
        spotter = _spotter(connection, router, FakeRetriever(), [], clock, cadence_seconds=1.0)
        clock.now = 100.0
        await spotter.on_final_segment("them", "   ")
        await spotter.flush()  # empty window: flush is a no-op
        assert router.calls == []
    finally:
        await connection.close()


def test_question_normalisation_and_tolerant_parse_table() -> None:
    assert normalise_question("What is the MARCH price??") == "what is the march price"
    assert normalise_question("  what   is\tthe march price ") == "what is the march price"
    assert parse_spotted_questions("[1, 2]") == []
    assert parse_spotted_questions(json.dumps({"questions": []})) == []
    assert parse_spotted_questions(
        json.dumps({"questions": [{"text": "Q?", "asked_by": "narrator"}]})
    ) == [("Q?", "unknown")]  # unknown speaker labels stay honest
    assert parse_spotted_questions(
        json.dumps({"questions": [{"text": " Q? ", "asked_by": "me"}]})
    ) == [("Q?", "me")]
