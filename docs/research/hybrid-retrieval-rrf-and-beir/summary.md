# Hybrid sparse+dense retrieval + Reciprocal Rank Fusion

**Sources (exact citations):**
- Cormack, Clarke & Buettcher, "Reciprocal Rank Fusion outperforms Condorcet and individual Rank Learning Methods", SIGIR 2009. https://plg.uwaterloo.ca/~gvcormac/cormacksigir09-rrf.pdf
- Thakur, Reimers, Rücklé, Srivastava, Gurevych, "BEIR: A Heterogeneous Benchmark for Zero-shot Evaluation of Information Retrieval Models", NeurIPS 2021 Datasets & Benchmarks. arXiv:2104.08663
- Elastic Search Labs, "Improving information retrieval in the Elastic Stack: Hybrid retrieval" (2023, BEIR-based). https://www.elastic.co/search-labs/blog/improving-information-retrieval-elastic-stack-hybrid

**Findings (faithful):**
- RRF formula, exact: `RRFscore(d ∈ D) = Σ_{r ∈ R} 1 / (k + r(d))`, with **k = 60**. Fuses ranks, not scores — avoids incomparable score scales (BM25 unbounded vs cosine ∈ [−1,1]). Training-free; beat Condorcet fusion and learned-rank methods (2009).
- BM25 (Robertson & Zaragoza 2009), as computed by SQLite FTS5 `bm25()`:
  `score(D,Q) = Σ_i IDF(q_i) · f(q_i,D)(k1+1) / [f(q_i,D) + k1(1 − b + b·|D|/avgdl)]`, k1 ∈ [1.2, 2.0], b = 0.75.
- BEIR: **no single retriever wins across domains**; dense models strong in-domain often underperform BM25 zero-shot out-of-domain.
- Elastic: RRF hybrid ≈ **+20% average nDCG@10 over BM25 alone**, ~+3% over a learned-sparse encoder, improves over both constituents across all subsets; recommends k=60 as calibration-free default.

**Best parts to take for Omni:** RRF(k=60) over FTS5-BM25 top-50 + sqlite-vec top-50 is the M3
baseline retriever. Meeting transcripts (proper nouns, company names, dates) are exactly BEIR's
out-of-domain regime where dense-only fails — hybrid is mandatory, not optional.
