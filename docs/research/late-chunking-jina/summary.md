# Late chunking (long-context embedding then chunk)

**Source (exact citation):** Günther et al. (Jina AI), "Late Chunking: Contextual Chunk Embeddings
Using Long-Context Embedding Models", 2024. arXiv:2409.04701. https://arxiv.org/html/2409.04701v3

**Findings (faithful):**
- Method: embed the whole document with a long-context model, THEN pool token embeddings per chunk —
  each chunk embedding sees full-document context.
- Measured relative retrieval improvement over naive chunking, averaged across 3 models × 4 datasets:
  **+3.63% (sentence-boundary), +3.46% (fixed-size), +2.70% (semantic chunking)**.
- Requires a long-context embedder (e.g. jina-v2, 8K tokens). bge-small-en-v1.5 caps at 512 tokens,
  so the technique's benefit is mostly unavailable without switching embedders.

**Best parts to take for Omni:** the gain (~3%) is an order of magnitude smaller than contextual
prefixing (35–49%) and gated on an embedder swap. **Defer** — adopt heading-aware chunking with
deterministic contextual prefixes now; revisit late chunking only if a long-context embedder wins
an experiment branch.
