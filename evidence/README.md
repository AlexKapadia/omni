# Omni — Evidence Showcase

This folder **proves and shows off** how good Omni is, to a peer-reviewed standard.
Every number here is a **real measurement of the real engine**, produced by a
committed harness and regenerable from committed data — nothing is hand-typed or
fabricated. Where the system is honestly weaker than its final design (dense
retrieval weights not yet shipped), it is measured **and labelled** as such rather
than flattered.

> **Self-contained + separable.** This folder is a standalone unit. Its
> analysis/plotting dependencies live only in `requirements-analysis.txt` and an
> isolated venv — they are **never** added to the engine's runtime manifest
> (`pyproject.toml` / `uv.lock`), so the showcase can be lifted out without
> touching the product.

---

## Headline results (all measured, all reproducible)

| Capability | Result | Where |
|---|---|---|
| **Retrieval quality** (BM25 tier) | Recall@5 **1.000** lexical / **0.667** paraphrase (overall 0.909), MRR 0.853 | `data/retrieval_quality_bm25.json` |
| **Retrieval latency** | p50 **0.78 ms**, p99 **1.92 ms** (n=1,375) — far under the 20 ms budget | `figures/fig_retrieval_latency_bm25.*` |
| **Retrieval scaling** | corpus ×**53.7** (30→1,610 notes) → p50 latency ×**3.6** (sub-linear) | `figures/fig_retrieval_latency_scaling.*` |
| **STT chunk-merge** | fidelity **1.000**, transcript reconstruction **1.000**; p50 **0.042 ms** | `figures/fig_stt_chunk_merge_latency.*` |
| **Router cost** | Decimal-exact — **0 mismatches** vs an independent rational cross-check (24 grid points) | `data/router_cost_and_fallback.json` |
| **Router — live** | **15 real** provider calls, **$0.00080723** total (cap $0.50), 0 fallbacks | `data/router_live_sample.json` |
| **Ask citation exactness** | **1.000** over 55 answers; **0** hallucinated markers survived | `figures/fig_ask_pipeline_latency.*` |
| **Dictation guard** | accuracy **1.000**, **0 false-negatives** over 1,020 adversarial cases | `figures/fig_dictation_faithfulness_confusion.*` |
| **Determinism** | all 5 deterministic paths: exactly **1** distinct output over repeated runs | `data/determinism.json` |
| **Test suite** | **950** Python + **408** TypeScript = **1,358** cases; **86.7%** line / **78.2%** branch coverage (measured) | `data/test_suite_inventory.json` |

---

## Folder layout

```
evidence/
  measure/     # measurement harnesses (import the REAL engine, headless) -> data/*.json
  data/        # committed raw results; figures + this README derive only from these
  figures/     # 12 figures, each PNG + interactive HTML (shared plotly.min.js)
  diagrams/    # 8 monochrome flow diagrams, each PNG + HTML, + the SVG toolkit
  requirements-analysis.txt   # analysis-ONLY deps (isolated; never in the runtime manifest)
  ruff.toml    # self-contained lint config for the folder
```

Run order: `measure/*` write `data/*.json`; `figures/build_all_figures.py` and
`diagrams/build_*` read `data/` (and the source tree, for diagrams) to render the
visuals. See **Reproduce** below.

---

## What each artifact proves

### Retrieval (`measure_retrieval_quality_bm25.py`, `measure_retrieval_latency_scaling.py`)
Runs the **real** `engine.index.HybridRrfRetriever` + `VaultIndexerService` over a
synthetic, PII-free labelled vault (20 seed notes + 30 distractors, 55 golden
queries). Reports note-level Recall@k, nDCG@k and MRR with 95% bootstrap CIs, split
into **lexical** vs **paraphrase** queries, plus a latency distribution and a
size-scaling curve. The lexical/paraphrase split is the honest story: BM25 is
perfect on lexical overlap and drops on pure paraphrase — exactly the
vocabulary-mismatch gap the dense tier is designed to close.

### STT chunk-merge (`measure_stt_chunk_merge_latency_and_fidelity.py`)
Drives the real `StreamingChunkMerger` headless (no GPU, no Parakeet) over 40
synthetic overlapping-window segments. Proves **fidelity** (every output token is a
verbatim input token; order monotonic) and **reconstruction** (the merged
transcript equals the intended words with overlap duplicates removed, none
dropped), and measures merge latency.

### Router (`measure_router_cost_and_fallback.py`, `measure_router_live_bounded_sample.py`)
Cost is checked against an **independent `fractions.Fraction`** computation across
a token grid and every priced model — a match to the last digit proves the money
path carries zero floating-point error. The fallback matrix drives the real
`ProviderRouter` with scripted clients to record retry/backoff/cascade per error
class. The **live** harness makes a small, metered set of **real** provider calls
(hard $0.50 cap; keys read from `.env` by the harness, never printed) and reports
the true spend.

### Ask-Omni (`measure_ask_latency_and_citation_exactness.py`)
Real `AskOmniAnswerService` + BM25 retriever, with a scripted synthesiser that
deliberately emits one valid citation and one **hallucinated dangling** marker per
answer. Proves the safety invariant *"a citation can never point at nothing"*:
every invented marker is stripped, every real citation's provenance matches the
cited chunk exactly.

### Dictation guard (`measure_dictation_faithfulness_guard.py`)
Real `cleanup_output_is_faithful` over a hand-labelled accept/refuse table plus a
seeded 500-iteration property sweep (1,020 cases total). The safety number is
**false-negatives = 0**: a hallucinated cleanup is never accepted as faithful.

### Determinism (`measure_determinism_proofs.py`)
Chunk-merge, VAD gating, router cost, the dictation guard, and BM25 ranking each run
many times on fixed inputs; every path yields exactly one distinct output.

### Test suite (`measure_test_suite_inventory.py`)
AST/parse count over the real repo, bucketed by rigour markers
(property/fuzz/determinism/injection/fail-closed/boundary/race/toctou), plus
`coverage.py --branch` measured over the real pytest suite (950 tests, 0 failures).

---

## Honest caveats (read these)

- **Dense retrieval is not yet active on this machine.** Omni's retriever is
  architecturally hybrid (BM25 ⊕ bge-small dense, RRF-fused), but the bge-small ONNX
  weights are absent here, so — by the engine's own fail-closed design — the dense
  list is empty and fusion collapses to **BM25 only**. Every retrieval result is
  labelled accordingly; the paraphrase-query gap quantifies exactly what the dense
  tier will recover. Re-running with the weights present measures the full hybrid
  with no change to the harness.
- **Synthetic data only.** All corpora, golden sets, and dictation cases are
  fabricated (no real PII, no private conversations) per the project's data rules.
  Numbers characterise the *system's behaviour*, not real user content.
- **STT measures the merge/gating logic, not model transcription accuracy.** The GPU
  Parakeet path needs the heavy `stt` extra + hardware and is out of scope for this
  headless showcase.
- **The live router sample is small and bounded** (15 calls, ~$0.0008) — enough to
  demonstrate real cost/latency/fallback wiring, not a load test. The reported spend
  is the true measured total.
- **Coverage is 86.7% line / 78.2% branch**, below the 90/85 *target* gate (which is
  staged to land in CI). Reported as measured, not as the aspiration. The over-limit
  files flagged by the inventory (`vault_indexer_service.py`,
  `live_capture_service.py`, `approval_cards_gateway.py` — all >300 lines) are
  pre-existing and noted here rather than changed by this lane.

---

## Reproduce

Two isolated environments — the engine venv runs the measurements; a throwaway
analysis venv renders the visuals.

```bash
# 1. Measurements (engine venv; headless, hermetic except the opt-in live sample)
PYTHONPATH=<repo-root> <engine-venv>/python evidence/measure/run_all_measurements.py
<engine-venv>/python evidence/measure/measure_router_live_bounded_sample.py   # real calls, $0.50 cap

# 2. Isolated analysis venv (plotting/diagram deps ONLY — never the runtime manifest)
python -m venv evidence/.evidence-venv
evidence/.evidence-venv/Scripts/pip install -r evidence/requirements-analysis.txt

# 3. Visuals (analysis venv)
evidence/.evidence-venv/Scripts/python evidence/figures/build_all_figures.py
evidence/.evidence-venv/Scripts/python evidence/diagrams/build_diagrams_pipeline.py
evidence/.evidence-venv/Scripts/python evidence/diagrams/build_diagrams_agents_system.py
```

The measurement harnesses are `ruff` + `mypy --strict` clean. Coverage of the raw
`coverage.py` report is summarised in `data/coverage_summary.json`; the multi-MB raw
report and the isolated venv are gitignored.
