"""Omni index layer — the AI-facing memory over the vault and transcripts.

Purpose: implements the M3 retrieval architecture ratified in
``docs/research/m3-retrieval-architecture-recommendation.md``: hybrid
RRF-fused BM25 (SQLite FTS5) + dense (bge-small via sqlite-vec) retrieval
over deterministically contextualized, heading-aware chunks, with a
structured entity/temporal/frontmatter route consulted FIRST, a free
structural graph from Obsidian's own wikilinks, and a chat-tier-only
rerank hook. Entirely in-process SQLite.

Pipeline position: reads the user's vault markdown and finalised
``transcript_segments``; serves M3's Ask-Omni service and the live
mid-meeting answerer. Entity rows are POPULATED by the extraction
pipeline (engine/agents, later); this layer reads them.

Security invariants upheld package-wide:
- Local-only: notes, transcripts, chunks, and embeddings never leave the
  machine; retrieval and indexing are fully in-process.
- All note/transcript/query content is untrusted DATA: parameterised SQL
  everywhere, FTS5 query syntax neutralised, nothing interpreted.
- Heavy optional dependencies (sqlite-vec, tokenizers, watchdog) fail
  CLOSED with actionable errors; they are tracked in
  docs/progress/pending-deps.txt and mocked at protocol boundaries in
  unit tests.
- Exact citation contract: every retrieved chunk carries
  ``note_path · L<start>-<end>`` (en dash in the rendered string) with
  1-based inclusive lines whose span is the chunk's verbatim source slice.
"""

from engine.index.bge_small_onnx_embedder import (
    EMBEDDING_DIMENSIONS,
    BgeSmallOnnxEmbedder,
    EmbedderProtocol,
)
from engine.index.hybrid_rrf_retriever import (
    TIER_CHAT,
    TIER_LIVE,
    HybridRrfRetriever,
    RerankerProtocol,
    reciprocal_rank_fusion,
)
from engine.index.index_layer_errors import IndexDependencyMissingError, IndexLayerError
from engine.index.markdown_heading_aware_chunker import Chunk, chunk_markdown_note
from engine.index.retrieved_chunk_types import RetrievedChunk, format_citation
from engine.index.sqlite_vec_store import SqliteVecStore, VectorStoreProtocol
from engine.index.structured_query_router import RouteDecision, classify_query
from engine.index.structured_sql_lookup_executor import (
    execute_structured_lookup,
    route_structured_query,
)
from engine.index.vault_indexer_service import IndexingReport, VaultIndexerService

__all__ = [
    "EMBEDDING_DIMENSIONS",
    "TIER_CHAT",
    "TIER_LIVE",
    "BgeSmallOnnxEmbedder",
    "Chunk",
    "EmbedderProtocol",
    "HybridRrfRetriever",
    "IndexDependencyMissingError",
    "IndexLayerError",
    "IndexingReport",
    "RerankerProtocol",
    "RetrievedChunk",
    "RouteDecision",
    "SqliteVecStore",
    "VaultIndexerService",
    "VectorStoreProtocol",
    "chunk_markdown_note",
    "classify_query",
    "execute_structured_lookup",
    "format_citation",
    "reciprocal_rank_fusion",
    "route_structured_query",
]
