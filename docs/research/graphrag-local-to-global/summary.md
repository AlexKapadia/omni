# Graph-augmented retrieval: GraphRAG vs free structural graphs

**Sources (exact citations):**
- Edge, Trinh, Cheng, Bradley et al. (Microsoft), "From Local to Global: A Graph RAG Approach to
  Query-Focused Summarization", 2024. arXiv:2404.16130
- LightRAG / LazyGraphRAG cost overview (secondary — vendor/Microsoft claims):
  https://learnopencv.com/lightrag/

**Findings (faithful):**
- GraphRAG: LLM-extracted entity graph + community summaries gives "substantial improvements over
  a conventional RAG baseline for comprehensiveness and diversity" on **global sensemaking
  questions** over ~1M-token corpora. Local (entity-anchored) search serves targeted questions.
- Cost of the LLM graph build ≈ **$20–40 per 1M tokens (gpt-4o)** (secondary). Cheaper variants:
  LightRAG ≈ $0.50/1M tokens; LazyGraphRAG ≈ 0.1% of extraction cost at comparable accuracy
  (secondary — confirm first-party before relying on these numbers).

**Best parts to take for Omni:** **Obsidian already IS a graph** — wikilinks give a structural
graph for free, deterministic and local. Take: graph expansion as a cheap SQL join (wikilinked
neighbours + same-entity chunks around top hybrid candidates), fed by the entity table from the
extraction pass. **Reject** full LLM graph builds for v1 (cost, indexing latency, cloud dependency
vs local-first). Revisit LightRAG-style dual-level retrieval only if global-thematic queries prove
important on the golden set.
