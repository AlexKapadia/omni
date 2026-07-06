# Embedding model selection (MTEB and small local models)

**Sources (exact citations):**
- Muennighoff, Tazi, Magne, Reimers, "MTEB: Massive Text Embedding Benchmark", 2023. arXiv:2210.07316
- BAAI bge-small-en-v1.5 model card (2023). https://huggingface.co/BAAI/bge-small-en-v1.5
- Zhang et al. (Alibaba), "Qwen3 Embedding: Advancing Text Embedding and Reranking Through
  Foundation Models", 2025. arXiv:2506.05176
- Snowflake, snowflake-arctic-embed-m model card.

**Findings (faithful):**
- MTEB is the standard multi-task embedding benchmark; leaderboard is live and shifts — check at
  decision time, not from memory.
- bge-small-en-v1.5: 384-dim, ~33M params, ~130 MB, 512-token context — strong, fast CPU pick;
  MTEB average ≈ 62 (⚠ secondary recollection — confirm on live leaderboard).
- Qwen3-Embedding-0.6B: 32K context, tops sub-1GB open models on 2025 boards (~64 on a multilingual
  track — secondary; confirm). snowflake-arctic-embed-m also competitive at similar size.
- A long-context embedder would additionally unlock late chunking (see late-chunking-jina/).

**Best parts to take for Omni:** **keep bge-small-en-v1.5 for M3 v1** — proven, tiny, CPU-fast,
384-dim keeps the sqlite-vec index small. Stand up Qwen3-Embedding-0.6B and arctic-embed-m on
`experiment/` branches and decide by golden-set numbers (contract §3.4), not leaderboard deltas.
