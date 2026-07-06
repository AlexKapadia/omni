# Contextual Retrieval (Anthropic)

**Source (exact citation):** Anthropic Engineering, "Introducing Contextual Retrieval", 2024
(first-party). https://www.anthropic.com/engineering/contextual-retrieval

**Findings (faithful):**
- Method: prepend chunk-specific explanatory context (50–100 tokens, LLM-written) to each chunk
  before embedding ("Contextual Embeddings") and before BM25 indexing ("Contextual BM25").
- Measured top-20-chunk retrieval **failure rate: 5.7% → 3.7% (−35%)** with contextual embeddings;
  **→ 2.9% (−49%)** adding contextual BM25; **→ 1.9% (−67%)** adding a reranker (Cohere).
- Top-20 retrieval outperformed top-5 and top-10. Gemini and Voyage embeddings "particularly
  effective". Context generation cost **$1.02 per 1M document tokens** with prompt caching.

**Best parts to take for Omni:** capture most of the gain **deterministically and free** — Obsidian
gives structure: prepend note title + heading breadcrumb + date + key frontmatter to every chunk
before embedding/FTS. Reserve LLM-written context for high-value notes, generated offline on the
RTX 4070. Also adopt: retrieve wider (top-20+) before fusion/rerank.
