"""Hybrid retriever: real FTS5 + mocked dense side, RRF behaviour, tiers.

The BM25 half is REAL (stdlib FTS5 over the 0004 schema, populated by the
real indexer); the dense half is a deterministic test double at the
VectorStoreProtocol/EmbedderProtocol boundary (sqlite-vec pending). Claims
under test: consensus documents outrank single-source ones, the reranker
hook fires ONLY on the chat tier, and explicit dense-absence degrades to
BM25-only instead of failing.
"""

from collections.abc import Sequence
from pathlib import Path

import aiosqlite

from engine.index.hybrid_rrf_retriever import (
    TIER_CHAT,
    TIER_LIVE,
    HybridRrfRetriever,
)
from engine.index.retrieved_chunk_types import RetrievedChunk
from engine.index.vault_indexer_service import VaultIndexerService
from engine.storage import apply_migrations, open_sqlite_connection


class FakeEmbedder:
    def embed_batch(self, texts: Sequence[str]) -> list[list[float]]:
        return [[0.5] * 384 for _ in texts]


class FakeVectorStore:
    """Returns a preset dense ranking; records the requested k."""

    def __init__(self, ranking: list[int]) -> None:
        self.ranking = ranking
        self.requested_k: int | None = None

    async def upsert_chunk_embeddings(
        self, pairs: Sequence[tuple[int, Sequence[float]]]
    ) -> None:  # pragma: no cover - not exercised here
        raise AssertionError("retriever must never write embeddings")

    async def delete_chunk_embeddings(self, chunk_ids: Sequence[int]) -> None:
        raise AssertionError("retriever must never delete embeddings")

    async def knn_chunk_ids(
        self, query_embedding: Sequence[float], top_k: int
    ) -> list[tuple[int, float]]:
        assert len(query_embedding) == 384
        self.requested_k = top_k
        return [(cid, 0.1 * i) for i, cid in enumerate(self.ranking, start=1)]


class RecordingReranker:
    def __init__(self) -> None:
        self.calls: list[tuple[str, list[int]]] = []

    async def rerank(
        self, query: str, candidates: Sequence[RetrievedChunk]
    ) -> list[RetrievedChunk]:
        self.calls.append((query, [c.chunk_id for c in candidates]))
        return list(reversed(candidates))  # detectable reordering


async def _indexed_db(
    tmp_path: Path, tmp_db_path: Path, real_migrations_dir: Path
) -> tuple[aiosqlite.Connection, dict[str, list[int]]]:
    """Three real notes indexed by the real indexer; returns chunk ids per note."""
    await apply_migrations(tmp_db_path, real_migrations_dir)
    connection = await open_sqlite_connection(tmp_db_path)
    vault = tmp_path / "vault"
    vault.mkdir()
    notes = {
        "budget.md": "# Budget\nThe quarterly budget review covers spending.\n",
        "roadmap.md": "# Roadmap\nThe roadmap covers milestones and spending.\n",
        "recipes.md": "# Recipes\nA soup recipe with lentils.\n",
    }
    paths = []
    for name, body in notes.items():
        path = vault / name
        path.write_text(body, encoding="utf-8")
        paths.append(path)
    await VaultIndexerService(connection, vault).index_changed_files(paths)
    ids: dict[str, list[int]] = {}
    for name in notes:
        cursor = await connection.execute(
            "SELECT id FROM chunks WHERE note_path = ? ORDER BY id", (name,)
        )
        ids[name] = [int(r[0]) for r in await cursor.fetchall()]
        await cursor.close()
    return connection, ids


async def test_consensus_chunk_outranks_single_source_chunks(
    tmp_path: Path, tmp_db_path: Path, real_migrations_dir: Path
) -> None:
    connection, ids = await _indexed_db(tmp_path, tmp_db_path, real_migrations_dir)
    try:
        roadmap_id = ids["roadmap.md"][0]
        recipes_id = ids["recipes.md"][0]
        # BM25 on "spending" matches budget+roadmap; dense says roadmap+recipes:
        # roadmap appears in BOTH rankings and must fuse to the top.
        store = FakeVectorStore([roadmap_id, recipes_id])
        retriever = HybridRrfRetriever(connection, store, FakeEmbedder())
        results = await retriever.retrieve("spending", enable_graph_expansion=False)
        assert results[0].chunk_id == roadmap_id
        assert results[0].retrieval_source == "hybrid_rrf"
        assert results[0].score > results[1].score
        assert store.requested_k == 50  # dense top-50 per the recommendation
        returned = {r.chunk_id for r in results}
        assert {ids["budget.md"][0], recipes_id} <= returned
    finally:
        await connection.close()


async def test_live_tier_never_calls_the_reranker(
    tmp_path: Path, tmp_db_path: Path, real_migrations_dir: Path
) -> None:
    connection, ids = await _indexed_db(tmp_path, tmp_db_path, real_migrations_dir)
    try:
        reranker = RecordingReranker()
        retriever = HybridRrfRetriever(
            connection, FakeVectorStore([ids["roadmap.md"][0]]), FakeEmbedder(), reranker
        )
        await retriever.retrieve("spending", tier=TIER_LIVE, enable_graph_expansion=False)
        assert reranker.calls == []  # live tier holds the <2 s budget
    finally:
        await connection.close()


async def test_chat_tier_reranks_the_pool_and_trims_to_top_n(
    tmp_path: Path, tmp_db_path: Path, real_migrations_dir: Path
) -> None:
    connection, ids = await _indexed_db(tmp_path, tmp_db_path, real_migrations_dir)
    try:
        reranker = RecordingReranker()
        retriever = HybridRrfRetriever(
            connection, FakeVectorStore([ids["recipes.md"][0]]), FakeEmbedder(), reranker
        )
        results = await retriever.retrieve(
            "spending", tier=TIER_CHAT, top_n=2, enable_graph_expansion=False
        )
        assert len(reranker.calls) == 1
        query, pool_ids = reranker.calls[0]
        assert query == "spending"
        assert len(pool_ids) >= 2
        # The reranker's order (reversed) is honoured, trimmed to top_n.
        assert [r.chunk_id for r in results] == list(reversed(pool_ids))[:2]
    finally:
        await connection.close()


async def test_chat_tier_without_reranker_falls_back_to_fused_order(
    tmp_path: Path, tmp_db_path: Path, real_migrations_dir: Path
) -> None:
    connection, ids = await _indexed_db(tmp_path, tmp_db_path, real_migrations_dir)
    try:
        retriever = HybridRrfRetriever(
            connection, FakeVectorStore([ids["roadmap.md"][0]]), FakeEmbedder()
        )
        results = await retriever.retrieve(
            "spending", tier=TIER_CHAT, enable_graph_expansion=False
        )
        assert results  # reranker model lands later; fused order until then
        assert results[0].chunk_id == ids["roadmap.md"][0]
    finally:
        await connection.close()


async def test_explicit_dense_absence_degrades_to_bm25_only(
    tmp_path: Path, tmp_db_path: Path, real_migrations_dir: Path
) -> None:
    connection, ids = await _indexed_db(tmp_path, tmp_db_path, real_migrations_dir)
    try:
        retriever = HybridRrfRetriever(connection, vector_store=None, embedder=None)
        results = await retriever.retrieve("lentils", enable_graph_expansion=False)
        assert [r.chunk_id for r in results] == ids["recipes.md"][:1]
    finally:
        await connection.close()


async def test_every_result_carries_the_exact_citation_contract(
    tmp_path: Path, tmp_db_path: Path, real_migrations_dir: Path
) -> None:
    connection, _ids = await _indexed_db(tmp_path, tmp_db_path, real_migrations_dir)
    try:
        retriever = HybridRrfRetriever(connection, vector_store=None, embedder=None)
        results = await retriever.retrieve("spending covers")
        assert results
        for result in results:
            expected = (  # en dash: the UI contract, not a typo
                f"{result.note_path} · L{result.line_start}–{result.line_end}"  # noqa: RUF001
            )
            assert result.citation == expected  # middle dot + EN DASH, exact
    finally:
        await connection.close()
