# M3 Retrieval Architecture — Evidence-Backed Recommendation

> CRO synthesis, 2026-07-06. Question: is there a better AI-facing memory layer over the
> Obsidian vault than plain dense vector search? **Yes — decisively.** Per-source evidence
> lives in the sibling folders; this file is the binding recommendation for M3.

## Verdict

Hybrid **RRF-fused BM25 + dense retrieval**, over **deterministically contextualized,
heading-aware chunks**, with a **structured entity/temporal index consulted first**, a
**free structural graph from Obsidian's own wikilinks**, and a **cross-encoder reranker
gated to the chat tier**. All in-process in SQLite (FTS5 + sqlite-vec). Obsidian stays the
human layer; this is the AI layer over the same content.

## Index tables (all SQLite)

1. `chunks` — note_path, heading_path breadcrumb, line_start/line_end, text,
   `contextualized_text` (deterministic prefix: title + heading breadcrumb + date + frontmatter), mtime
2. `chunks_fts` — FTS5 external-content over contextualized_text → BM25
3. `chunks_vec` — sqlite-vec vec0 embeddings of contextualized_text (bge-small-en-v1.5, 384-dim)
4. `entities` (canonical_name, type ∈ person/company/commitment/date, aliases) + `entity_mentions`
5. `notes_meta` — frontmatter fields + created/modified → structured + temporal lookup
6. `links` — (src_note, dst_note) from wikilinks → free structural graph

## Query pipeline

1. **Route** (deterministic + tiny model): entity / temporal / frontmatter queries →
   structured SQL lookup FIRST (exact, fast, exact citations). Semantic → hybrid.
2. **Hybrid retrieve:** FTS5 BM25 top-50 + dense top-50 → **RRF fuse, k=60**
   (`RRFscore(d) = Σ_r 1/(k + r(d))`, Cormack et al. 2009) → top ~25.
3. **Graph expansion:** join in wikilinked-neighbour + same-entity chunks (cheap SQL).
4. **Rerank — chat tier only:** bge-reranker-v2-m3 over top ~25 → top 5–8.
   **Live tier skips reranking** to hold the <2 s budget (or tiny top-10 GPU rerank if benched fast enough).
5. **Cite:** every chunk carries note_path + line range + heading_path → exact file+line citation.
6. **Generate** via the tri-provider router.

Two latency tiers: **Live** = route + hybrid RRF only. **Chat** = full pipeline; HyDE opt-in
for hard queries only.

## Why each choice won (the numbers)

- **Hybrid over dense-only:** BEIR (NeurIPS 2021, arXiv:2104.08663) — dense retrievers that win
  in-domain often lose to BM25 out-of-domain; Omni's transcripts (proper nouns, dates, action
  phrasing) are exactly that regime. Elastic's BEIR-based report: RRF hybrid ≈ **+20% nDCG@10 over
  BM25**, improving on both constituents; k=60 calibration-free.
- **Contextualized chunks:** Anthropic Contextual Retrieval (2024, first-party) — top-20 retrieval
  failure 5.7% → 3.7% (−35%) with contextual embeddings, → 2.9% (−49%) adding contextual BM25,
  → 1.9% (−67%) adding rerank. Omni captures most of this **deterministically** (title/heading/
  date/frontmatter prefix) at zero LLM cost; LLM-written context optional/offline on the 4070.
- **Reranker (chat tier):** typical +5–15 nDCG@10 (BGE/FlagEmbedding docs), corroborated by the
  Anthropic 49%→67% step. Latency incompatible with the live budget → tier-gated.
- **Structural graph, not GraphRAG:** GraphRAG (arXiv:2404.16130) wins on global sensemaking but
  the LLM graph build costs ~$20–40/1M tokens and adds a cloud dependency — while **Obsidian's
  wikilinks are already a graph**, free and deterministic.
- **Heading-aware chunking:** late chunking (arXiv:2409.04701) adds only ~+2.7–3.6% and needs a
  long-context embedder (bge-small caps at 512 tok) — heading-aware + contextual prefix is the
  better local ROI.
- **Structured-first routing:** exact SQL on entities/dates beats any semantic method on precision
  for "what's Priya's number" / "what did we agree in March" — and is Omni's stated core use.

## Rejected (and why)

- **Dense-only** — fragile on names/exact tokens (BEIR).
- **Score-based fusion** — incomparable score scales; RRF fuses ranks.
- **Full Microsoft GraphRAG** — cost, indexing latency, cloud dependency vs local-first.
- **Multi-query & MMR** — ARAGOG (arXiv:2404.01037) found multi-query *reduced* precision, MMR no gain.
- **HyDE in live path** — extra LLM round-trip breaks <2 s; opt-in for chat only.
- **ColBERT late interaction** — per-token vector storage cost; revisit only if v2-m3 underperforms.
- **Embedder swap now** — bge-small-en-v1.5 stays for v1 (proven, 33M params, CPU-fast, 384-dim);
  Qwen3-Embedding-0.6B (arXiv:2506.05176) and snowflake-arctic-embed-m go on experiment branches.

## Golden-set evaluation plan (proves the choice, §3.4)

- **Metrics:** Recall@20, nDCG@10, MRR; citation-exactness (cited line contains the answer);
  answer faithfulness; p50/p95 latency; determinism across repeated runs.
- **Data:** synthetic vault + synthetic/public transcripts ONLY (no PII). ~150–300 labelled
  queries across classes: entity lookup, temporal, commitment/action, semantic QA, cross-note
  synthesis, adversarial (injection embedded in a note, duplicate names, missing frontmatter,
  mid-capture transcript gaps). Gold note(s)+line(s) per query.
- **Procedure:** each config on its own `experiment/<approach>` branch, same golden set:
  dense-only vs RRF-hybrid vs +contextual-prefix vs +graph vs +rerank; bge-small vs Qwen3-0.6B
  vs arctic-embed. Winner merges; numbers recorded here.

## Open flags (resolve before locking M3)

- bge-reranker-v2-m3 CPU latency & param count came from secondary sources — confirm first-party.
- Bench whether a tiny reranker fits the live <2 s budget on the 4070.
- ARAGOG results are boxplot-only — directional; re-derive on Omni's golden set.
- Current MTEB scalars for candidate embedders — confirm on the live leaderboard at experiment time.
