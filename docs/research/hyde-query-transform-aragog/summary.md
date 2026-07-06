# Query transformation: HyDE, multi-query, decomposition (ARAGOG evaluation)

**Sources (exact citations):**
- Gao, Ma, Lin, Callan, "Precise Zero-Shot Dense Retrieval without Relevance Labels" (HyDE), 2022.
  arXiv:2212.10496
- Eibich, Nagpal, Fred-Ojala, "ARAGOG: Advanced RAG Output Grading", 2024. arXiv:2404.01037.
  https://arxiv.org/html/2404.01037v1

**Findings (faithful):**
- HyDE: an LLM writes a hypothetical answer document; embed THAT instead of the query — improves
  zero-shot dense retrieval.
- ARAGOG: **HyDE + LLM-rerank was the "most potent" combination for retrieval precision**;
  sentence-window retrieval had high median precision but lower answer similarity. Crucially:
  **multi-query REDUCED precision vs the naive baseline; MMR showed no advantage; Cohere rerank
  "did not demonstrate anticipated benefits" in their setup.** Results reported as boxplots with
  ANOVA/Tukey significance — no exact scalars extractable; treat rankings as directional.

**Best parts to take for Omni:** every query transform costs an extra LLM round-trip —
incompatible with the <2 s live budget, and multi-query can actively hurt. **Skip all query
transforms in the live tier; offer HyDE as opt-in for hard Ask-Omni chat queries only.**
Re-derive on Omni's own golden set rather than trusting boxplot rankings.
