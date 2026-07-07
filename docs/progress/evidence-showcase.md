# Progress Tracker — evidence/ Showcase Lane

**North Star:** A committed, self-contained `evidence/` folder that PROVES and shows off how good Omni is, to a peer-reviewed standard — real measurements of the real system, rigorous presentation (PNG + interactive HTML graphs, monochrome flow diagrams), honest caveats. Analysis/plotting deps isolated from runtime.

**Branch:** `feature/evidence` (worktree `C:\dev\Omni-evidence`). Runtime engine env: `C:\dev\Omni\.venv` (py3.11). Analysis env: `evidence/.evidence-venv` (isolated, plotting only).

## Resume here
Measurement layer COMPLETE (9 harnesses green, ruff+mypy strict clean, all data captured, committed). NEXT: build figures (evidence/figures/, PNG+HTML from committed data), then diagrams (evidence/diagrams/, monochrome HTML+PNG), then evidence/README.md.

## Headline numbers (REAL, measured)
- Retrieval BM25: Recall@5 overall 0.909 (lexical 1.0, paraphrase 0.667), MRR 0.853; latency p50 ~1-3ms (proves <20ms).
- Retrieval scaling: corpus x53.7 -> p50 latency x2.5 (sub-linear).
- STT chunk-merge: fidelity 1.0, reconstruction 1.0, p50 ~0.06ms.
- Router cost: 24 grid points, 0 rational mismatches (Decimal exact); 5 fallback scenarios.
- Router LIVE: 15 real Groq calls, $0.00080723 total, p50 136ms, 0 fallbacks.
- Ask citation exactness: 1.0 over 55 answers, 0 dangling survived.
- Dictation guard: accuracy 1.0, 0 false-negatives over 510 cases.
- Determinism: all 5 paths distinct_outputs=1.
- Tests: 950 py + 408 ts = 1358 cases; line coverage 86.7% (measured).

## Plan / checklist
- [x] Worktree + evidence/ scaffold + requirements-analysis.txt (isolated) + analysis venv
- [x] Map engine APIs (router/ask, stt/dictation, index/retrieval) via Explore agents
- [x] Harness: STT chunk-merge latency + fidelity (headless, no GPU)
- [x] Harness: retrieval quality (Recall@k/nDCG/MRR) + latency, lexical vs paraphrase split
- [x] Harness: router cost (Decimal, Fraction cross-check) + fallback matrix
- [x] Harness: router LIVE bounded sample ($0.50 cap, real spend reported)
- [x] Harness: ask citation-exactness + retrieval-stage latency
- [x] Harness: dictation faithfulness-guard confusion matrix
- [x] Harness: determinism proofs (chunk-merge, vad gating, cost, guard, retrieval)
- [x] Harness: test/coverage stats (measured 86.7% line coverage)
- [x] ruff + mypy strict clean on evidence/measure/*.py
- [ ] Figures: PNG + interactive HTML each (means +/- 95% CI, labelled)
- [ ] Diagrams: monochrome HTML+PNG per component + whole system
- [ ] evidence/README.md showcase index (headline numbers, method, caveats)
- [ ] Verify analysis deps absent from pyproject/uv.lock
- [ ] Commit + push feature/evidence

## Key facts (from API maps)
- Retrieval: hybrid RRF (structured-SQL-first then dense+lexical), MAX_CONTEXT_CHUNKS=8. Dense=bge-small via sqlite-vec — MUST verify if model present or BM25-only (index agent pending).
- Router: Decimal-exact pricing (model_pricing.py), inject own ledger-recorder + clock for deterministic; real sample via build_provider_clients(ProviderKeyStore()), cheapest = live_extraction (Groq llama-3.3). Env keys GROQ_API_KEY, GEMINI_API_KEY.
- Ask: AskOmniAnswerService.answer(query) -> AskAnswer w/ AskLatencyBreakdown(retrieval_ms, synthesis_ms); citation exactness via citation_marker_mapping.py (source [i] == chunks[i-1]).
- STT: StreamingChunkMerger (pure, headless) + WordToken/TranscribedWindow; TranscriptionLatencyTracker for p50/p95/p99; VadGatingStateMachine deterministic.
- Dictation: cleanup_output_is_faithful(raw, cleaned, dict_terms) -> bool — pure deterministic guard (content-word containment, growth cap 1.4x+24).

## Caveats to state honestly
- Synthetic data only (no PII) for golden sets.
- Dense retrieval: label BM25-only if bge-small not wired (pending index agent).
- Router real sample is bounded (small n, $0.50 cap) — report real spend.
- STT measures the deterministic merge/gating logic, not GPU Parakeet transcription accuracy.
