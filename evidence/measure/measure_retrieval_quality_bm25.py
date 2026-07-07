"""Measure retrieval quality + latency of Omni's real index layer (BM25 tier).

HONEST SCOPE: Omni's retriever is architecturally hybrid (BM25 FTS5 fused with a
dense bge-small ranking via reciprocal rank fusion). On this machine the
bge-small ONNX weights are absent, so the dense list is empty and fusion
collapses to pure BM25 order — a documented, fail-closed degradation in the
engine itself (HybridRrfRetriever._dense_ranking returns [] with no embedder).
This harness therefore measures the **BM25 lexical tier only** and labels every
output accordingly. When the dense weights ship, re-running with an embedder
measures the full hybrid with no code change here.

It runs the REAL VaultIndexerService + HybridRrfRetriever against a synthetic,
PII-free labelled vault and reports note-level Recall@k, nDCG@k, MRR (mean with
95% bootstrap CI) plus a retrieval latency distribution (p50/p95/p99).
"""

from __future__ import annotations

import asyncio
import json
import tempfile
import time
from pathlib import Path
from typing import Any

from engine.index import HybridRrfRetriever, VaultIndexerService
from engine.index.hybrid_rrf_retriever import TIER_LIVE
from engine.storage import apply_migrations, open_sqlite_connection
from statistics_helpers import (
    mean_with_bootstrap_ci,
    ndcg_at_k,
    nearest_rank_percentile_ms,
    recall_at_k,
    reciprocal_rank,
)
from synthetic_vault_corpus import build_synthetic_vault

_DATA_DIR = Path(__file__).resolve().parent.parent / "data"
_K_VALUES = (1, 3, 5, 10)
_TOP_N = 10
_LATENCY_REPEATS = 25  # per query, after a warmup, to build a latency distribution


def _ranked_note_paths(chunks: list[Any]) -> list[str]:
    """Collapse ranked chunks to their notes, first-appearance order preserved.

    Relevance is labelled at note granularity (the answer is "which note"), the
    standard treatment when documents are chunked.
    """
    seen: list[str] = []
    for chunk in chunks:
        path = chunk.note_path
        if path not in seen:
            seen.append(path)
    return seen


async def _run() -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="omni-eval-retrieval-") as tmp:
        tmp_path = Path(tmp)
        vault_root = tmp_path / "vault"
        vault_root.mkdir()
        db_path = tmp_path / "eval.db"
        migrations_dir = Path(__file__).resolve().parents[2] / "migrations"

        written, golden = build_synthetic_vault(vault_root)
        await apply_migrations(db_path, migrations_dir)
        connection = await open_sqlite_connection(db_path)
        try:
            indexer = VaultIndexerService(connection, vault_root)  # BM25-only: no embedder
            report = await indexer.index_changed_files(written)

            # Stable note_path -> int id map for the ranking-metric helpers.
            note_ids = {p.relative_to(vault_root).as_posix(): i for i, p in enumerate(written)}
            retriever = HybridRrfRetriever(connection, None, None)  # honest BM25-only wiring

            kinds = ("overall", "lexical", "paraphrase")
            recall: dict[str, dict[int, list[float]]] = {
                kind: {k: [] for k in _K_VALUES} for kind in kinds
            }
            ndcg: dict[str, dict[int, list[float]]] = {
                kind: {k: [] for k in _K_VALUES} for kind in kinds
            }
            rr_values: dict[str, list[float]] = {kind: [] for kind in kinds}
            latencies_ms: list[float] = []

            for gq in golden:
                relevant = {note_ids[p] for p in gq.relevant_note_paths}
                chunks = await retriever.retrieve(
                    gq.query, tier=TIER_LIVE, top_n=_TOP_N, enable_graph_expansion=False
                )
                ranked = [note_ids[p] for p in _ranked_note_paths(list(chunks))]
                rr = reciprocal_rank(ranked, relevant)
                for kind in ("overall", gq.kind):
                    for k in _K_VALUES:
                        recall[kind][k].append(recall_at_k(ranked, relevant, k))
                        ndcg[kind][k].append(ndcg_at_k(ranked, relevant, k))
                    rr_values[kind].append(rr)

            # Warm the cache, then time repeated retrievals to build a distribution.
            for gq in golden:
                await retriever.retrieve(gq.query, top_n=_TOP_N, enable_graph_expansion=False)
            for _ in range(_LATENCY_REPEATS):
                for gq in golden:
                    start = time.perf_counter()
                    await retriever.retrieve(
                        gq.query, top_n=_TOP_N, enable_graph_expansion=False
                    )
                    latencies_ms.append((time.perf_counter() - start) * 1000.0)
        finally:
            await connection.close()

    def summarise(values: list[float]) -> dict[str, float | int]:
        mean, lo, hi = mean_with_bootstrap_ci(values)
        return {"mean": mean, "ci95_low": lo, "ci95_high": hi, "n": len(values)}

    kinds = ("overall", "lexical", "paraphrase")
    return {
        "method": "BM25 (SQLite FTS5) lexical tier only — dense bge-small weights "
        "absent on this machine, so RRF fusion collapses to BM25 order (honest "
        "documented degradation). Note-level relevance on a synthetic PII-free vault. "
        "Golden set split into lexical-overlap vs deliberate-paraphrase queries; the "
        "paraphrase gap is the vocabulary-mismatch limit the dense tier is meant to close.",
        "retriever": "engine.index.HybridRrfRetriever (real), graph_expansion disabled",
        "corpus": {
            "notes_indexed": report.indexed_notes,
            "chunks_written": report.chunks_written,
            "golden_queries": len(golden),
            "lexical_queries": sum(1 for g in golden if g.kind == "lexical"),
            "paraphrase_queries": sum(1 for g in golden if g.kind == "paraphrase"),
            "top_n": _TOP_N,
        },
        "recall_at_k": {
            kind: {str(k): summarise(recall[kind][k]) for k in _K_VALUES} for kind in kinds
        },
        "ndcg_at_k": {
            kind: {str(k): summarise(ndcg[kind][k]) for k in _K_VALUES} for kind in kinds
        },
        "mrr": {kind: summarise(rr_values[kind]) for kind in kinds},
        "latency_ms": {
            "n_measurements": len(latencies_ms),
            "mean_ci": summarise(latencies_ms),
            "p50": nearest_rank_percentile_ms(latencies_ms, 50),
            "p95": nearest_rank_percentile_ms(latencies_ms, 95),
            "p99": nearest_rank_percentile_ms(latencies_ms, 99),
            "raw_ms": [round(v, 4) for v in latencies_ms],
        },
    }


def main() -> None:
    result = asyncio.run(_run())
    _DATA_DIR.mkdir(parents=True, exist_ok=True)
    out = _DATA_DIR / "retrieval_quality_bm25.json"
    out.write_text(json.dumps(result, indent=2), encoding="utf-8")
    recall = result["recall_at_k"]
    mrr = result["mrr"]
    lat = result["latency_ms"]
    print(f"wrote {out}")
    for kind in ("overall", "lexical", "paraphrase"):
        print(
            f"  [{kind:10}] Recall@5={recall[kind]['5']['mean']:.3f}  MRR={mrr[kind]['mean']:.3f}"
        )
    print(f"  retrieval p50/p95/p99 = {lat['p50']:.3f}/{lat['p95']:.3f}/{lat['p99']:.3f} ms")


if __name__ == "__main__":
    main()
