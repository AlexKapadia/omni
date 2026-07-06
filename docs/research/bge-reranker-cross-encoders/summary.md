# Cross-encoder rerankers (BGE family, ColBERT-style late interaction)

**Sources (exact citations):**
- BAAI BGE / FlagEmbedding reranker documentation. https://bge-model.com/tutorial/5_Reranking/5.1.html
- Corroborating first-party datapoint: Anthropic Contextual Retrieval (2024) — adding a reranker
  took retrieval failure reduction from −49% to −67%.

**Findings (faithful):**
- Cross-encoders jointly encode (query, chunk) → far more accurate relevance than bi-encoder
  cosine, at O(N) forward passes over the candidate set.
- Typical lift across MTEB/BEIR-style evals: **+5 to +15 nDCG@10** (BGE docs).
- bge-reranker-v2-m3 latency ≈ **130 ms per 16-pair batch on CPU** — ⚠ secondary source; and one
  secondary source's "278M params" claim looks wrong (v2-m3 is XLM-RoBERTa-large-based, ~568M).
  **Confirm both first-party before locking M3.**
- ColBERT-style late interaction: more accurate still, but stores per-token vectors (large index).

**Best parts to take for Omni:** run bge-reranker-v2-m3 over the top ~25 fused candidates in the
**Ask-Omni chat tier only**; the live-meeting tier skips it (or a benched top-10 GPU rerank) to
hold <2 s. Skip ColBERT for v1 — revisit only if single-vector rerank underperforms on the golden set.
