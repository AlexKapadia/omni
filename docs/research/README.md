# Omni Research Library — M3 Retrieval / AI-Facing Memory Layer

**Research question (product owner):** Obsidian markdown is the HUMAN-readable layer. Is there a
better AI-FACING memory/retrieval layer over the same content — more accurate and faster at finding
data — than plain dense vector search?

**Corpus:** user's Obsidian vault (markdown + frontmatter + wikilinks) + all meeting transcripts.
**Constraints:** fully local (SQLite-centric, no servers), CPU-friendly at query time (<2 s during
live meetings; RTX 4070 available for indexing), must serve (a) live mid-meeting Q&A, (b) Ask-Omni
chat with exact source citations, (c) entity lookups (people, companies, commitments, dates).

Every source is filed one-folder-per-source with a faithful structured summary, exact citation, and a
"best parts to take" note. The synthesis and recommendation live in
`m3-retrieval-architecture-recommendation.md`.

## Library index

| Folder | Source | Method family | One-line finding |
| --- | --- | --- | --- |
| `hybrid-retrieval-rrf-and-beir/` | Cormack et al. 2009 (RRF); BEIR (Thakur et al. 2021); Elastic hybrid retrieval report | Sparse+dense fusion | RRF fusion of BM25 + dense beats either alone; Elastic reports up to +20% nDCG@10 over BM25. |
| `anthropic-contextual-retrieval/` | Anthropic Engineering, 2024 | Contextual chunking + hybrid + rerank | Prepending LLM-written context per chunk cuts top-20 retrieval failures 35% (embeddings), 49% (+BM25), 67% (+rerank). |
| `bge-reranker-cross-encoders/` | BAAI BGE model docs + FlagEmbedding; reranker benchmarks | Cross-encoder reranking | +5–15 nDCG@10 typical lift; bge-reranker-v2-m3 (568 MB) ~130 ms/16-pair batch on CPU. |
| `late-chunking-jina/` | Günther et al. 2024 (arXiv:2409.04701) | Chunking | Late chunking gives +2.7–3.6% retrieval over naive chunking; needs long-context embedder. |
| `hyde-query-transform-aragog/` | Gao et al. 2022 (HyDE); Eibich et al. 2024 (ARAGOG) | Query transformation | HyDE+rerank helps precision; multi-query and MMR did NOT beat naive baseline in ARAGOG. |
| `graphrag-local-to-global/` | Edge et al. 2024 (arXiv:2404.16130); LightRAG/LazyGraphRAG | Graph-augmented retrieval | GraphRAG wins on global/thematic questions but LLM graph build is costly ($20–40 / 1M tok); cheap structural graphs (wikilinks) capture most of Omni's value. |
| `sqlite-vec-fts5-hybrid-local/` | Alex Garcia, sqlite-vec docs 2024 | Local-first feasibility | Native SQLite hybrid: FTS5 (BM25) + sqlite-vec + RRF entirely in-process, no server. |
| `mteb-embedding-model-selection/` | MTEB (Muennighoff et al. 2023); BGE; Qwen3-Embedding (Zhang et al. 2025); Snowflake Arctic Embed | Embedding model choice | bge-small-en-v1.5 still a solid CPU pick; Qwen3-Embedding-0.6B / snowflake-arctic-embed-m are stronger modern small options. |

## How to read this library
1. Start with `m3-retrieval-architecture-recommendation.md` for the decision and the numbers behind it.
2. Drill into any folder's `summary.md` for the primary evidence and exact citation.

**Sourcing discipline (CRO):** primary papers / official docs / benchmark reports only. Where a
number could only be sourced from secondary write-ups, it is labelled as such and flagged for
first-party confirmation. No blog folklore is treated as evidence.
