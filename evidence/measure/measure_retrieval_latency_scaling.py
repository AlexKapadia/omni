"""Measure how BM25 retrieval latency scales with vault size.

Claim under test: retrieval stays fast as the vault grows — the SQLite FTS5
inverted index makes a query's cost depend on the matching postings, not on a
linear scan of every note. This harness indexes vaults of increasing size and
measures median / p95 retrieval latency at each, producing a scaling curve the
evidence plots against linear and constant references.

Real engine.index.HybridRrfRetriever (BM25 tier only — bge-small weights absent),
synthetic PII-free corpus.
"""

from __future__ import annotations

import asyncio
import json
import tempfile
import time
from pathlib import Path
from typing import Any

from engine.index import HybridRrfRetriever, VaultIndexerService
from engine.storage import apply_migrations, open_sqlite_connection
from statistics_helpers import mean_with_bootstrap_ci, nearest_rank_percentile_ms
from synthetic_vault_corpus import build_synthetic_vault

_DATA_DIR = Path(__file__).resolve().parent.parent / "data"
_DISTRACTOR_SIZES = (10, 40, 90, 190, 390, 790, 1590)  # -> ~30..1610 total notes
_REPEATS = 20


async def _measure_size(distractors: int) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="omni-eval-scaling-") as tmp:
        tmp_path = Path(tmp)
        vault_root = tmp_path / "vault"
        vault_root.mkdir()
        db_path = tmp_path / "scale.db"
        migrations_dir = Path(__file__).resolve().parents[2] / "migrations"

        written, golden = build_synthetic_vault(vault_root, distractor_count=distractors)
        await apply_migrations(db_path, migrations_dir)
        connection = await open_sqlite_connection(db_path)
        try:
            report = await VaultIndexerService(connection, vault_root).index_changed_files(written)
            retriever = HybridRrfRetriever(connection, None, None)
            for gq in golden:  # warm
                await retriever.retrieve(gq.query, top_n=8, enable_graph_expansion=False)
            latencies: list[float] = []
            for _ in range(_REPEATS):
                for gq in golden:
                    start = time.perf_counter()
                    await retriever.retrieve(gq.query, top_n=8, enable_graph_expansion=False)
                    latencies.append((time.perf_counter() - start) * 1000.0)
        finally:
            await connection.close()

    mean, lo, hi = mean_with_bootstrap_ci(latencies)
    return {
        "notes_indexed": report.indexed_notes,
        "chunks": report.chunks_written,
        "measurements": len(latencies),
        "mean_ms": mean,
        "ci95_low_ms": lo,
        "ci95_high_ms": hi,
        "p50_ms": nearest_rank_percentile_ms(latencies, 50),
        "p95_ms": nearest_rank_percentile_ms(latencies, 95),
    }


async def _run() -> dict[str, Any]:
    points = [await _measure_size(d) for d in _DISTRACTOR_SIZES]
    first, last = points[0], points[-1]
    size_ratio = last["notes_indexed"] / first["notes_indexed"]
    latency_ratio = last["p50_ms"] / first["p50_ms"] if first["p50_ms"] else float("inf")
    return {
        "component": "engine.index.HybridRrfRetriever BM25 tier (SQLite FTS5)",
        "method": "Index vaults of increasing size; measure retrieval latency at each. "
        "Sub-linear latency growth vs note-count growth evidences inverted-index scaling.",
        "points": points,
        "corpus_growth_factor": size_ratio,
        "p50_latency_growth_factor": latency_ratio,
        "sub_linear": latency_ratio < size_ratio,
    }


def main() -> None:
    result = asyncio.run(_run())
    _DATA_DIR.mkdir(parents=True, exist_ok=True)
    out = _DATA_DIR / "retrieval_scaling.json"
    out.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(f"wrote {out}")
    print(
        f"  corpus grew {result['corpus_growth_factor']:.1f}x, "
        f"p50 latency grew {result['p50_latency_growth_factor']:.2f}x "
        f"(sub_linear={result['sub_linear']})"
    )
    for p in result["points"]:
        print(f"    notes={p['notes_indexed']:5d}  p50={p['p50_ms']:.3f}ms  p95={p['p95_ms']:.3f}")


if __name__ == "__main__":
    main()
