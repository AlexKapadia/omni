"""THE CORE retriever: FTS5 BM25 + dense KNN fused with Reciprocal Rank Fusion.

Purpose: the M3 recommendation's hybrid pipeline — BM25 top-50 (SQLite
FTS5, real and in-process) + dense top-50 (via the mockable vector-store
boundary) fused by RRF with k=60 (Cormack et al. 2009), then optional
structural graph expansion, then a chat-tier-only rerank hook.
Pipeline position: called by M3's Ask-Omni service (chat tier) and the
live mid-meeting answerer (live tier); consumes ``sqlite_vec_store`` and
``bge_small_onnx_embedder`` outputs over the 0004 schema.

Two latency tiers (binding):
- ``live``  — route + hybrid RRF only (no rerank; holds the <2 s budget).
- ``chat``  — full pipeline; reranked when a reranker is wired (the
  reranker MODEL lands later — interface only here).

RRF formula (exact, tested): ``score(d) = Σ_r 1/(k + rank_r(d))`` with
1-based ranks over each constituent ranking, k = 60. Ties broken by
ascending chunk id (deterministic output, documented).

Security invariants:
- FTS5 MATCH input is sanitised to quoted bare terms — user queries are
  untrusted and must not reach FTS5's query syntax (injection defence;
  a syntax crash on ``"`` or ``NEAR(`` would be a denial of service).
- Missing dense dependencies FAIL CLOSED with a clear error unless the
  store/embedder was explicitly configured as absent (honest FTS-only
  degradation is a caller decision, never a silent one).
"""

import asyncio
import re
from collections.abc import Sequence
from typing import Protocol

import aiosqlite

from engine.index.bge_small_onnx_embedder import EmbedderProtocol
from engine.index.chunk_rows_repository import fetch_retrieved_chunks
from engine.index.index_layer_errors import IndexLayerError
from engine.index.retrieved_chunk_types import RetrievedChunk
from engine.index.sqlite_vec_store import VectorStoreProtocol
from engine.index.structural_graph_expander import expand_with_structural_graph

RRF_K = 60
FTS_CANDIDATES = 50
DENSE_CANDIDATES = 50
FUSED_POOL_SIZE = 25  # rerank pool per the recommendation (top ~25)
DEFAULT_TOP_N = 8
TIER_LIVE = "live"
TIER_CHAT = "chat"
RETRIEVAL_SOURCE_HYBRID = "hybrid_rrf"
RETRIEVAL_SOURCE_RERANKED = "reranked"

_WORD_TOKEN = re.compile(r"\w+", re.UNICODE)


class RerankerProtocol(Protocol):
    """Chat-tier rerank hook; the cross-encoder model lands later (M3+)."""

    async def rerank(
        self, query: str, candidates: Sequence[RetrievedChunk]
    ) -> list[RetrievedChunk]:
        """Return candidates re-ordered best-first (may re-score them)."""
        ...


def sanitize_fts_match_query(query: str) -> str:
    """Reduce an untrusted query to FTS5-safe quoted terms, OR-joined.

    Every word token is double-quoted (an FTS5 string), so operators
    (AND/OR/NOT/NEAR), column filters (``col:``), parentheses, ``*`` and
    stray quotes are neutralised — they either become quoted terms or are
    dropped. OR-joining favours recall; BM25 ranks the matches. An empty
    result means "no searchable terms" and the caller returns no rows.
    """
    tokens = _WORD_TOKEN.findall(query)
    return " OR ".join(f'"{token}"' for token in tokens)


def reciprocal_rank_fusion(
    rankings: Sequence[Sequence[int]], k: int = RRF_K
) -> list[tuple[int, float]]:
    """Fuse rankings: score(d) = Σ 1/(k + rank(d)), rank 1-based.

    Accumulation order is the given rankings order (float addition order
    is part of the exactness contract the tests pin down). Sorted by
    descending score, ties by ascending id — fully deterministic.
    """
    if k <= 0:
        raise IndexLayerError(f"RRF k must be positive, got {k}")
    scores: dict[int, float] = {}
    for ranking in rankings:
        for rank, doc_id in enumerate(ranking, start=1):
            scores[doc_id] = scores.get(doc_id, 0.0) + 1.0 / (k + rank)
    return sorted(scores.items(), key=lambda item: (-item[1], item[0]))


class HybridRrfRetriever:
    """Hybrid retrieval over the 0004 schema with tiered post-processing.

    ``vector_store``/``embedder`` may be ``None`` — an EXPLICIT caller
    decision meaning "dense side not available yet" (deps pending); the
    retriever then fuses over BM25 alone and results still carry exact
    citations. If they are provided but their dependency is missing, the
    underlying ``IndexDependencyMissingError`` propagates (fail closed).
    """

    def __init__(
        self,
        connection: aiosqlite.Connection,
        vector_store: VectorStoreProtocol | None,
        embedder: EmbedderProtocol | None,
        reranker: RerankerProtocol | None = None,
    ) -> None:
        self._connection = connection
        self._vector_store = vector_store
        self._embedder = embedder
        self._reranker = reranker

    async def _bm25_ranking(self, match_query: str) -> list[int]:
        """FTS5 BM25 top-FTS_CANDIDATES chunk ids, best first."""
        if not match_query:
            return []
        cursor = await self._connection.execute(
            # bm25(): numerically smaller = better match (SQLite FTS5 docs).
            "SELECT rowid FROM chunks_fts WHERE chunks_fts MATCH ? "
            "ORDER BY bm25(chunks_fts) LIMIT ?",
            (match_query, FTS_CANDIDATES),
        )
        rows = await cursor.fetchall()
        await cursor.close()
        return [int(row[0]) for row in rows]

    async def _dense_ranking(self, query: str) -> list[int]:
        """Dense top-DENSE_CANDIDATES chunk ids via the vector store."""
        if self._vector_store is None or self._embedder is None:
            return []  # explicit FTS-only configuration (documented above)
        # ONNX inference is CPU-bound and sync; keep the event loop live.
        vectors = await asyncio.to_thread(self._embedder.embed_batch, [query])
        matches = await self._vector_store.knn_chunk_ids(vectors[0], DENSE_CANDIDATES)
        return [chunk_id for chunk_id, _distance in matches]

    async def retrieve(
        self,
        query: str,
        tier: str = TIER_LIVE,
        top_n: int = DEFAULT_TOP_N,
        enable_graph_expansion: bool = True,
    ) -> list[RetrievedChunk]:
        """Run the tiered hybrid pipeline; every result carries a citation.

        Unknown tiers are refused (deny by default), not guessed at.
        """
        if tier not in (TIER_LIVE, TIER_CHAT):
            raise IndexLayerError(f"unknown retrieval tier {tier!r}")
        bm25_ids = await self._bm25_ranking(sanitize_fts_match_query(query))
        dense_ids = await self._dense_ranking(query)
        fused = reciprocal_rank_fusion([bm25_ids, dense_ids])
        pool_ids = [doc_id for doc_id, _ in fused[:FUSED_POOL_SIZE]]
        pool = await fetch_retrieved_chunks(
            self._connection, pool_ids, RETRIEVAL_SOURCE_HYBRID, scores=dict(fused)
        )
        expansion: list[RetrievedChunk] = []
        if enable_graph_expansion and pool:
            expansion = await expand_with_structural_graph(self._connection, pool)
        if tier == TIER_CHAT and self._reranker is not None:
            reranked = await self._reranker.rerank(query, [*pool, *expansion])
            return list(reranked[:top_n])
        # Live tier (and chat before the reranker model lands): fused
        # order, trimmed, plus capped structural expansion.
        return [*pool[:top_n], *expansion]
