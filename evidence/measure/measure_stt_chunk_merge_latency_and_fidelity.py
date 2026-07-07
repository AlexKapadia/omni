"""Measure Omni's streaming STT chunk-merge: latency distribution + fidelity.

This exercises the REAL engine.stt.StreamingChunkMerger — the deterministic
logic that stitches overlapping Parakeet windows into a single transcript,
deduping words that appear in the overlap of two adjacent windows. It runs
entirely headless (pure Python, no GPU, no Parakeet weights), so it measures the
merge algorithm itself, not model transcription accuracy.

Two things are proved:
  * FIDELITY — every output token is an input token verbatim (object identity),
    order is monotonic, and the merged transcript reconstructs the intended word
    sequence exactly (overlap duplicates removed, none dropped). This is the
    correctness that makes the merge safe to trust.
  * LATENCY — wall-clock to merge a full segment, over many synthetic segments
    of varied length, reported as p50/p95/p99 with a mean 95% CI.
"""

from __future__ import annotations

import json
import random
import time
from pathlib import Path
from typing import Any

from engine.stt.streaming_chunk_merger import StreamingChunkMerger
from engine.stt.word_token_types import TranscribedWindow, WordToken
from statistics_helpers import mean_with_bootstrap_ci, nearest_rank_percentile_ms

_DATA_DIR = Path(__file__).resolve().parent.parent / "data"
_WINDOW_LEN_S = 4.0
_HOP_S = 3.2  # 0.8 s overlap between adjacent windows — Omni's default merge overlap
_WORD_DURATION_S = 0.35
_WORD_GAP_S = 0.05
_SEGMENT_WORD_COUNTS = tuple(range(10, 130, 3))  # varied segment lengths
_REPEATS_PER_SEGMENT = 30


def _build_ground_truth(rng: random.Random, word_count: int) -> list[WordToken]:
    """A synthetic spoken segment: distinct words at monotonically rising times."""
    words: list[WordToken] = []
    cursor = 0.0
    for i in range(word_count):
        text = f"word{i:04d}{rng.choice('abcdef')}"
        start = cursor
        end = start + _WORD_DURATION_S
        words.append(WordToken(text, start, end))
        cursor = end + _WORD_GAP_S
    return words


def _slice_into_overlapping_windows(words: list[WordToken]) -> list[TranscribedWindow]:
    """Cut the segment into overlapping windows the way a real assembler would.

    A word is emitted into every window whose time span contains its midpoint, so
    words in the overlap region appear in TWO adjacent windows — exactly the
    duplication the merger must resolve.
    """
    if not words:
        return []
    horizon = words[-1].t_end
    windows: list[TranscribedWindow] = []
    index = 0
    start = 0.0
    while start < horizon:
        end = start + _WINDOW_LEN_S
        in_window = tuple(w for w in words if start <= w.midpoint < end)
        if in_window:
            windows.append(TranscribedWindow(index, start, end, in_window))
            index += 1
        start += _HOP_S
    return windows


def _merge_once(windows: list[TranscribedWindow]) -> list[WordToken]:
    merger = StreamingChunkMerger(overlap_s=_WINDOW_LEN_S - _HOP_S)
    for window in windows:
        merger.add_window(window)
    return merger.flush()


def _run() -> dict[str, Any]:
    rng = random.Random(0x5EED)
    latencies_ms: list[float] = []
    fidelity_failures = 0
    reconstruction_failures = 0
    segments_checked = 0
    total_words_merged = 0

    for word_count in _SEGMENT_WORD_COUNTS:
        ground_truth = _build_ground_truth(rng, word_count)
        windows = _slice_into_overlapping_windows(ground_truth)
        input_identities = {id(w) for window in windows for w in window.words}

        # Correctness check once per segment (deterministic result).
        merged = _merge_once(windows)
        segments_checked += 1
        total_words_merged += len(merged)
        # Fidelity: every output token is a verbatim input object, order monotonic.
        if any(id(w) not in input_identities for w in merged):
            fidelity_failures += 1
        if any(merged[i].t_start > merged[i + 1].t_start for i in range(len(merged) - 1)):
            fidelity_failures += 1
        # Reconstruction: merged transcript equals the intended words, in order.
        if [w.text for w in merged] != [w.text for w in ground_truth]:
            reconstruction_failures += 1

        # Latency: time the full merge repeatedly to build a distribution.
        for _ in range(_REPEATS_PER_SEGMENT):
            start = time.perf_counter()
            _merge_once(windows)
            latencies_ms.append((time.perf_counter() - start) * 1000.0)

    mean, lo, hi = mean_with_bootstrap_ci(latencies_ms)
    return {
        "component": "engine.stt.StreamingChunkMerger (real, headless — no GPU / no Parakeet)",
        "method": "Synthetic overlapping-window segments (overlap 0.8 s). Fidelity by "
        "object identity + order; reconstruction = merged transcript equals intended "
        "word sequence with overlap duplicates removed and none dropped.",
        "segments_checked": segments_checked,
        "total_words_merged": total_words_merged,
        "fidelity_failures": fidelity_failures,
        "reconstruction_failures": reconstruction_failures,
        "fidelity_pass_rate": (segments_checked - fidelity_failures) / segments_checked,
        "reconstruction_pass_rate": (segments_checked - reconstruction_failures)
        / segments_checked,
        "latency_ms": {
            "n_measurements": len(latencies_ms),
            "mean": mean,
            "ci95_low": lo,
            "ci95_high": hi,
            "p50": nearest_rank_percentile_ms(latencies_ms, 50),
            "p95": nearest_rank_percentile_ms(latencies_ms, 95),
            "p99": nearest_rank_percentile_ms(latencies_ms, 99),
            "raw_ms": [round(v, 5) for v in latencies_ms],
        },
    }


def main() -> None:
    result = _run()
    _DATA_DIR.mkdir(parents=True, exist_ok=True)
    out = _DATA_DIR / "stt_chunk_merge.json"
    out.write_text(json.dumps(result, indent=2), encoding="utf-8")
    lat = result["latency_ms"]
    print(f"wrote {out}")
    print(
        f"  fidelity={result['fidelity_pass_rate']:.3f} "
        f"reconstruction={result['reconstruction_pass_rate']:.3f} "
        f"over {result['segments_checked']} segments"
    )
    print(f"  merge p50/p95/p99 = {lat['p50']:.4f}/{lat['p95']:.4f}/{lat['p99']:.4f} ms")


if __name__ == "__main__":
    main()
