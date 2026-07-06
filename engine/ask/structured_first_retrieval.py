"""Structured-first retrieval shared by Ask-Omni and the live spotter.

Purpose: the M3 recommendation's "route FIRST" step as one reusable
function — classify the query deterministically; entity/temporal/
frontmatter routes answer via EXACT SQL; everything else (and any
structured route that finds nothing) falls through to hybrid RRF with a
weak-result floor applied.
Pipeline position: between ``engine.index`` and both ask services, so the
chat and live paths route identically and are tested once.

Weak-retrieval floor (the honesty gate, tested at the boundary):
- Structured-SQL chunks are exact matches by construction — never floored.
- Hybrid chunks must carry an RRF score of at least
  ``MINIMUM_HYBRID_RRF_SCORE`` = 1/(RRF_K + WEAK_RANK_CUTOFF): the score a
  document earns by ranking WEAK_RANK_CUTOFF-th in a single constituent
  ranking. Anything weaker is dropped; if NO hybrid seed survives, graph
  expansions (their children) are dropped too and the result is empty —
  the caller then answers honestly instead of synthesising from noise.

Security: the query is untrusted data end-to-end — the router regex-scans
it, the executor binds it as SQL parameters, FTS5 input is sanitised in
the retriever. Nothing here interprets it.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date

import aiosqlite

from engine.ask.ask_service_protocols import ChunkRetrieverProtocol
from engine.index.hybrid_rrf_retriever import (
    RETRIEVAL_SOURCE_HYBRID,
    RRF_K,
)
from engine.index.retrieved_chunk_types import RetrievedChunk
from engine.index.structured_query_router import ROUTE_HYBRID
from engine.index.structured_sql_lookup_executor import (
    execute_structured_lookup,
    route_structured_query,
)

# Rank floor: a hybrid chunk must score at least as well as a rank-25
# single-list hit (consensus across lists compensates for deeper ranks).
WEAK_RANK_CUTOFF = 25
MINIMUM_HYBRID_RRF_SCORE = 1.0 / (RRF_K + WEAK_RANK_CUTOFF)


@dataclass(frozen=True)
class StructuredFirstResult:
    """Retrieved chunks plus WHICH route produced them (explainability)."""

    chunks: list[RetrievedChunk]
    route: str  # 'entity' | 'temporal' | 'frontmatter' | 'hybrid'


def apply_hybrid_score_floor(chunks: list[RetrievedChunk]) -> list[RetrievedChunk]:
    """Drop below-floor hybrid seeds; drop expansions when no seed survives.

    Order is preserved. Non-hybrid sources (structured_*, reranked) pass
    through untouched — the floor is a hybrid-rank concept only.
    """
    seeds = [
        chunk
        for chunk in chunks
        if chunk.retrieval_source != RETRIEVAL_SOURCE_HYBRID
        or chunk.score >= MINIMUM_HYBRID_RRF_SCORE
    ]
    hybrid_seed_survived = any(
        chunk.retrieval_source == RETRIEVAL_SOURCE_HYBRID for chunk in seeds
    )
    had_hybrid_seeds = any(
        chunk.retrieval_source == RETRIEVAL_SOURCE_HYBRID for chunk in chunks
    )
    if had_hybrid_seeds and not hybrid_seed_survived:
        # Graph expansions exist only as children of hybrid seeds; with every
        # seed floored, keeping the children would launder weak retrieval.
        return []
    return seeds


async def retrieve_structured_first(
    connection: aiosqlite.Connection,
    retriever: ChunkRetrieverProtocol,
    query: str,
    *,
    tier: str,
    top_n: int,
    enable_graph_expansion: bool,
    today: Callable[[], date] = date.today,
) -> StructuredFirstResult:
    """Classify, try exact SQL first, fall through to floored hybrid RRF.

    A structured route that returns rows is FINAL (exact citations, no
    semantic dilution). A structured route that finds nothing falls
    through to hybrid — an unresolved entity/date must not read as
    "nothing anywhere in the vault".
    """
    decision = await route_structured_query(connection, query, today())
    if decision.route != ROUTE_HYBRID:
        structured = await execute_structured_lookup(connection, decision)
        if structured:
            return StructuredFirstResult(chunks=structured[:top_n], route=decision.route)
    hybrid = await retriever.retrieve(
        query, tier=tier, top_n=top_n, enable_graph_expansion=enable_graph_expansion
    )
    return StructuredFirstResult(
        chunks=apply_hybrid_score_floor(hybrid)[:top_n], route=ROUTE_HYBRID
    )
