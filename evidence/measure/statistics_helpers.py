"""Peer-review-grade summary statistics for the evidence harnesses.

Why this exists: every harness reports DISTRIBUTIONS, not single points, so the
showcase can present means with 95% confidence intervals, exact nearest-rank
percentiles, and ranking-quality metrics (Recall@k, nDCG@k, MRR). Keeping the
maths in one audited, pure-stdlib module means the figures regenerate
deterministically from the committed raw data and every number is traceable to
a formula here — no hidden library behaviour.

Pure standard library only (math, statistics, random). No numpy, so this runs
identically under the engine runtime venv and needs no analysis dependency.
"""

from __future__ import annotations

import math
import random
import statistics
from collections.abc import Sequence


def nearest_rank_percentile_ms(samples: Sequence[float], percentile: float) -> float:
    """Exact nearest-rank percentile (NIST method), never interpolated.

    Every reported value is a REAL observation from the sample — the same
    definition Omni's own TranscriptionLatencyTracker uses — so p50/p95/p99 in
    the evidence match the engine's runtime semantics exactly.
    """
    if not samples:
        raise ValueError("percentile of an empty sample is undefined")
    if not 0.0 < percentile <= 100.0:
        raise ValueError("percentile must be in (0, 100]")
    ordered = sorted(samples)
    rank = math.ceil(percentile / 100.0 * len(ordered))
    return ordered[rank - 1]


def mean_with_bootstrap_ci(
    samples: Sequence[float],
    *,
    confidence: float = 0.95,
    resamples: int = 10_000,
    seed: int = 0xE71DE5CE,
) -> tuple[float, float, float]:
    """Return (mean, ci_low, ci_high) via the percentile bootstrap.

    The bootstrap is distribution-free — correct for the heavy-tailed latency
    samples the harnesses collect, where a normal-approx CI would understate the
    tail. Seeded so the interval is reproducible from the committed data.
    """
    if not samples:
        raise ValueError("cannot summarise an empty sample")
    point = statistics.fmean(samples)
    if len(samples) == 1:
        return (point, point, point)
    rng = random.Random(seed)
    n = len(samples)
    means: list[float] = []
    for _ in range(resamples):
        draw = [samples[rng.randrange(n)] for _ in range(n)]
        means.append(statistics.fmean(draw))
    means.sort()
    lo_idx = int((1.0 - confidence) / 2.0 * resamples)
    hi_idx = int((1.0 + confidence) / 2.0 * resamples) - 1
    return (point, means[lo_idx], means[hi_idx])


def wilson_score_interval(
    successes: int, trials: int, *, z: float = 1.959963984540054
) -> tuple[float, float, float]:
    """Wilson 95% CI for a proportion (accuracy / recall on a labelled set).

    Wilson (not the normal Wald interval) because it stays inside [0, 1] and is
    accurate for the small, high-accuracy samples the guard/citation harnesses
    produce — the correct choice for reporting a rate near 100%.
    """
    if trials <= 0:
        raise ValueError("cannot form a proportion CI with zero trials")
    p = successes / trials
    denom = 1.0 + z * z / trials
    centre = (p + z * z / (2 * trials)) / denom
    half = (z / denom) * math.sqrt(p * (1 - p) / trials + z * z / (4 * trials * trials))
    return (p, max(0.0, centre - half), min(1.0, centre + half))


def recall_at_k(ranked_ids: Sequence[int], relevant_ids: set[int], k: int) -> float:
    """Fraction of the relevant items recovered within the top-k results."""
    if not relevant_ids:
        raise ValueError("recall is undefined with no relevant items")
    top_k = set(ranked_ids[:k])
    return len(top_k & relevant_ids) / len(relevant_ids)


def reciprocal_rank(ranked_ids: Sequence[int], relevant_ids: set[int]) -> float:
    """Reciprocal rank of the FIRST relevant hit (0.0 if none) — the MRR term."""
    for position, item in enumerate(ranked_ids, start=1):
        if item in relevant_ids:
            return 1.0 / position
    return 0.0


def ndcg_at_k(ranked_ids: Sequence[int], relevant_ids: set[int], k: int) -> float:
    """Binary-relevance nDCG@k (Jarvelin & Kekalainen, 2002).

    DCG = sum over the top-k of rel_i / log2(i+1); normalised by the ideal DCG
    where every relevant item is ranked first. Reported alongside Recall and MRR
    because nDCG rewards putting the right chunk HIGH, which is what matters when
    only MAX_CONTEXT_CHUNKS=8 reach the model.
    """
    dcg = 0.0
    for position, item in enumerate(ranked_ids[:k], start=1):
        if item in relevant_ids:
            dcg += 1.0 / math.log2(position + 1)
    ideal_hits = min(len(relevant_ids), k)
    if ideal_hits == 0:
        return 0.0
    idcg = sum(1.0 / math.log2(i + 1) for i in range(1, ideal_hits + 1))
    return dcg / idcg
