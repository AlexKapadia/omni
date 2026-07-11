"""Structured-first passthrough: entity queries answer via exact SQL.

Claims under test: a query naming a known entity NEVER touches the hybrid
retriever — its chunks come from the exact entity lookup, are handed to
synthesis as numbered context, and cite the real note lines; a structured
route that finds NOTHING falls through to hybrid (an unresolved entity
must not read as "nothing anywhere"); the untrusted query text rides the
data channel only, never the instruction frame.
"""

import json
from pathlib import Path

import aiosqlite

from engine.ask.ask_omni_answer_service import AskOmniAnswerService
from engine.ask.ask_prompt_frames import ASK_SYNTHESIS_SYSTEM_FRAME
from engine.index.retrieved_chunk_types import RetrievedChunk
from engine.index.vault_indexer_service import VaultIndexerService
from engine.router.completion_contract import (
    ChatMessage,
    Provider,
    ProviderCompletion,
    RoutedCompletion,
    ToolSpec,
)
from engine.storage import apply_migrations, open_sqlite_connection

PHONE_LINE = "Phone: +44 7700 900123"


class FakeRouter:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, tuple[ChatMessage, ...]]] = []

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
        self.calls.append((task_type, system_frame, messages))
        completion = ProviderCompletion(
            text=json.dumps(
                {"headline": "Priya's number", "answer": "It is +44 7700 900123 [1]."}
            ),
            provider=Provider.GROQ,
            model="llama-3.3-70b-versatile",
            prompt_tokens=1,
            completion_tokens=1,
        )
        return RoutedCompletion(
            completion=completion,
            provider=Provider.GROQ,
            model="llama-3.3-70b-versatile",
            latency_ms=50,
        )


class RefusingRetriever:
    """Hybrid must not run on a structured hit — retrieval here is a bug."""

    def __init__(self) -> None:
        self.calls = 0

    async def retrieve(
        self,
        query: str,
        tier: str = "live",
        top_n: int = 8,
        enable_graph_expansion: bool = True,
    ) -> list[RetrievedChunk]:
        self.calls += 1
        return []


async def _db_with_person_note(
    tmp_path: Path, tmp_db_path: Path, real_migrations_dir: Path, *, with_mentions: bool
) -> aiosqlite.Connection:
    """Real indexer over a People note; entity rows inserted as the
    extraction pipeline (M4) will insert them."""
    await apply_migrations(tmp_db_path, real_migrations_dir)
    connection = await open_sqlite_connection(tmp_db_path)
    vault = tmp_path / "vault"
    vault.mkdir()
    note = vault / "priya-sharma.md"
    note.write_text(
        f"# Priya Sharma\n\n## Contact\n{PHONE_LINE}\nRole: procurement lead.\n",
        encoding="utf-8",
    )
    await VaultIndexerService(connection, vault).index_changed_files([note])
    cursor = await connection.execute(
        "INSERT INTO entities (canonical_name, entity_type, aliases_json)"
        " VALUES ('Priya Sharma', 'person', '[\"priya\"]')"
    )
    entity_id = int(cursor.lastrowid or 0)
    await cursor.close()
    if with_mentions:
        await connection.execute(
            "INSERT INTO entity_mentions (entity_id, chunk_id)"
            " SELECT ?, id FROM chunks WHERE note_path = 'priya-sharma.md'",
            (entity_id,),
        )
    await connection.commit()
    return connection


async def test_entity_query_bypasses_hybrid_and_cites_the_real_lines(
    tmp_path: Path, tmp_db_path: Path, real_migrations_dir: Path
) -> None:
    connection = await _db_with_person_note(
        tmp_path, tmp_db_path, real_migrations_dir, with_mentions=True
    )
    try:
        router = FakeRouter()
        retriever = RefusingRetriever()
        service = AskOmniAnswerService(connection, retriever, router)
        answer = await service.answer("What is Priya's phone number?")
        assert retriever.calls == 0  # structured passthrough: hybrid untouched
        assert len(router.calls) == 1
        task_type, system_frame, messages = router.calls[0]
        assert task_type == "ask_synthesis"
        # Injection posture: the frame is the constant; the query is DATA.
        assert system_frame == ASK_SYNTHESIS_SYSTEM_FRAME
        assert "Priya" not in system_frame
        assert "What is Priya's phone number?" in messages[0].content
        assert PHONE_LINE in messages[0].content  # the exact chunk was the context
        assert answer.no_answer is False
        assert answer.citations, "structured chunks must be citable"
        citation = answer.citations[0]
        assert citation.note_path == "priya-sharma.md"
        # Cited lines really contain the fact (citation-exactness invariant).
        note_lines = (tmp_path / "vault" / "priya-sharma.md").read_text().splitlines()
        cited = "\n".join(note_lines[citation.line_start - 1 : citation.line_end])
        assert PHONE_LINE in cited
    finally:
        await connection.close()


async def test_structured_route_with_no_rows_falls_through_to_hybrid(
    tmp_path: Path, tmp_db_path: Path, real_migrations_dir: Path
) -> None:
    connection = await _db_with_person_note(
        tmp_path, tmp_db_path, real_migrations_dir, with_mentions=False
    )
    try:
        router = FakeRouter()
        retriever = RefusingRetriever()
        service = AskOmniAnswerService(connection, retriever, router)
        answer = await service.answer("What is Priya's phone number?")
        # Known entity but zero mentions: exact SQL finds nothing, so the
        # semantic path gets its turn instead of a false "not in your notes".
        assert retriever.calls == 1
        assert answer.no_answer is True  # hybrid (empty here) stayed honest
        assert router.calls == []
    finally:
        await connection.close()
