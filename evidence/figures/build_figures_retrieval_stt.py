"""Build the retrieval + STT evidence figures (PNG + interactive HTML).

Reads only the committed evidence/data/*.json, so figures regenerate
deterministically. Analysis-only (matplotlib + plotly).
"""

from __future__ import annotations

from figure_style import dual_grouped_bar, dual_histogram, dual_scaling, load


def _ci_half(entry: dict[str, float]) -> float:
    """Half-width of the 95% CI, for symmetric matplotlib error bars."""
    return max(entry["mean"] - entry["ci95_low"], entry["ci95_high"] - entry["mean"])


def build_retrieval_quality() -> None:
    data = load("retrieval_quality_bm25")
    kinds = ("overall", "lexical", "paraphrase")
    metrics = ("Recall@1", "Recall@3", "Recall@5", "nDCG@5", "MRR")

    def values_for(kind: str) -> tuple[list[float], list[float]]:
        rec = data["recall_at_k"][kind]
        ndcg = data["ndcg_at_k"][kind]
        mrr = data["mrr"][kind]
        vals = [rec["1"]["mean"], rec["3"]["mean"], rec["5"]["mean"],
                ndcg["5"]["mean"], mrr["mean"]]
        errs = [_ci_half(rec["1"]), _ci_half(rec["3"]), _ci_half(rec["5"]),
                _ci_half(ndcg["5"]), _ci_half(mrr)]
        return vals, errs

    series = []
    for kind in kinds:
        vals, errs = values_for(kind)
        series.append((kind, vals, errs))
    corpus = data["corpus"]
    caption = (
        f"BM25 (SQLite FTS5) lexical tier only — dense bge-small weights absent, so RRF "
        f"collapses to BM25 (honest degradation). n={corpus['golden_queries']} golden queries "
        f"({corpus['lexical_queries']} lexical, {corpus['paraphrase_queries']} paraphrase) over "
        f"{corpus['notes_indexed']} synthetic notes. Bars: mean, error bars: 95% bootstrap CI."
    )
    dual_grouped_bar(
        "fig_retrieval_quality_bm25",
        "Retrieval quality — BM25 lexical tier (note-level relevance)",
        "score", metrics, series, caption, y_range=(0.0, 1.05),
    )


def build_retrieval_latency() -> None:
    data = load("retrieval_quality_bm25")
    lat = data["latency_ms"]
    caption = (
        f"Real engine.index.HybridRrfRetriever, BM25 tier. n={lat['n_measurements']} timed "
        f"retrievals over the synthetic vault. Every retrieval is well under the 20 ms live-answer "
        f"budget (p99={lat['p99']:.2f} ms)."
    )
    dual_histogram(
        "fig_retrieval_latency_bm25",
        "Retrieval latency distribution (BM25 tier)",
        "retrieval latency (ms)", lat["raw_ms"],
        [("p50", lat["p50"]), ("p95", lat["p95"]), ("p99", lat["p99"])], caption,
    )


def build_retrieval_scaling() -> None:
    data = load("retrieval_scaling")
    points = data["points"]
    x = [p["notes_indexed"] for p in points]
    y = [p["p50_ms"] for p in points]
    y_low = [p["ci95_low_ms"] for p in points]
    y_high = [p["ci95_high_ms"] for p in points]
    # Reference curves anchored at the smallest corpus: linear growth vs flat.
    base_notes, base_lat = x[0], y[0]
    linear = [base_lat * (n / base_notes) for n in x]
    constant = [base_lat for _ in x]
    caption = (
        f"Real BM25 retrieval over vaults from {x[0]} to {x[-1]} notes. Corpus grows "
        f"{data['corpus_growth_factor']:.0f}x while p50 latency grows only "
        f"{data['p50_latency_growth_factor']:.1f}x — strongly sub-linear (inverted-index scaling). "
        f"Dashed: linear and constant references."
    )
    dual_scaling(
        "fig_retrieval_latency_scaling",
        "Retrieval latency scales sub-linearly with vault size",
        x, y, y_low, y_high,
        [("linear reference", linear), ("constant reference", constant)], caption,
    )


def build_stt_merge_latency() -> None:
    data = load("stt_chunk_merge")
    lat = data["latency_ms"]
    caption = (
        f"Real engine.stt.StreamingChunkMerger, headless (no GPU/Parakeet). "
        f"n={lat['n_measurements']} merges over {data['segments_checked']} synthetic segments. "
        f"Fidelity {data['fidelity_pass_rate']:.3f} and transcript reconstruction "
        f"{data['reconstruction_pass_rate']:.3f} (every output token a verbatim input token; "
        f"overlap duplicates removed, none dropped)."
    )
    dual_histogram(
        "fig_stt_chunk_merge_latency",
        "STT chunk-merge latency distribution",
        "merge time per segment (ms)", lat["raw_ms"],
        [("p50", lat["p50"]), ("p95", lat["p95"]), ("p99", lat["p99"])], caption, bins=45,
    )


def main() -> None:
    build_retrieval_quality()
    build_retrieval_latency()
    build_retrieval_scaling()
    build_stt_merge_latency()
    print("built retrieval + STT figures")


if __name__ == "__main__":
    main()
