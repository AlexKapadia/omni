"""Chunk-merger core: overlap ownership, dedup guard, boundary-exact cuts.

The merger is the correctness-critical heart of streaming STT: these tests
pin the midpoint-cut contract (earlier window wins strictly before the
cut, later window wins at/after it), the jitter dedup guard with its exact
tolerance boundary, and the replay-rejection fail-closed path.
"""

import pytest

from engine.stt.streaming_chunk_merger import StreamingChunkMerger
from engine.stt.word_token_types import TranscribedWindow, WordToken


def w(text: str, t_start: float, t_end: float) -> WordToken:
    return WordToken(text=text, t_start=t_start, t_end=t_end)


def window(index: int, t_start: float, t_end: float, *words: WordToken) -> TranscribedWindow:
    return TranscribedWindow(index=index, t_start=t_start, t_end=t_end, words=tuple(words))


# Standard geometry: 4 s windows, 3.2 s hop, 0.8 s overlap. Window 1 starts
# at 3.2, so the cut between windows 0 and 1 sits at 3.2 + 0.4 = 3.6.
CUT_0_1 = 3.6


def test_single_window_flushes_all_words_in_midpoint_order() -> None:
    merger = StreamingChunkMerger(overlap_s=0.8)
    merger.add_window(window(0, 0.0, 4.0, w("world", 1.0, 1.4), w("hello", 0.2, 0.6)))
    assert [t.text for t in merger.flush()] == ["hello", "world"]


def test_overlap_ownership_earlier_window_wins_before_the_cut() -> None:
    """A word with midpoint just UNDER the cut keeps the earlier window's copy."""
    merger = StreamingChunkMerger(overlap_s=0.8)
    # Earlier window's version at midpoint 3.55 (< 3.6).
    merger.add_window(window(0, 0.0, 4.0, w("early-version", 3.4, 3.7)))
    # Later window disagrees about the same instant — must lose.
    merger.add_window(window(1, 3.2, 7.2, w("late-version", 3.35, 3.75), w("next", 4.0, 4.4)))
    texts = [t.text for t in merger.flush()]
    assert texts == ["early-version", "next"]


def test_overlap_ownership_later_window_wins_at_and_after_the_cut() -> None:
    """Boundary-exact: midpoint EXACTLY at the cut belongs to the later window."""
    merger = StreamingChunkMerger(overlap_s=0.8)
    # Earlier window's copy sits exactly at the cut (midpoint 3.6) — evicted.
    merger.add_window(window(0, 0.0, 4.0, w("stale", 3.45, 3.75)))
    merger.add_window(window(1, 3.2, 7.2, w("fresh", 3.45, 3.75)))
    assert [t.text for t in merger.flush()] == ["fresh"]


def test_word_timestamp_conflict_resolves_to_exactly_one_copy() -> None:
    """Two windows hear the same words with jittered times: no dupes, no drops."""
    merger = StreamingChunkMerger(overlap_s=0.8)
    merger.add_window(
        window(0, 0.0, 4.0, w("alpha", 3.0, 3.2), w("bravo", 3.3, 3.5), w("charlie", 3.6, 3.9))
    )
    # Window 1 re-hears bravo/charlie with ~60 ms jitter, plus new material.
    merger.add_window(
        window(
            1,
            3.2,
            7.2,
            w("bravo", 3.36, 3.56),
            w("charlie", 3.55, 3.85),
            w("delta", 4.2, 4.5),
        )
    )
    texts = [t.text for t in merger.flush()]
    assert texts == ["alpha", "bravo", "charlie", "delta"]


def test_dedup_guard_drops_literal_duplicate_straddling_the_cut() -> None:
    """Same word committed just before the cut AND re-heard just after it."""
    merger = StreamingChunkMerger(overlap_s=0.8)
    merger.add_window(window(0, 0.0, 4.0, w("Echo", 3.3, 3.5)))  # midpoint 3.4 < cut
    merger.add_window(window(1, 3.2, 7.2, w("echo", 3.5, 3.8), w("foxtrot", 4.0, 4.3)))
    texts = [t.text for t in merger.flush()]
    # Casefold match + midpoints 3.4 vs 3.65 (0.25 <= 0.3 tolerance) -> deduped,
    # committed copy (original casing) survives — text never rewritten.
    assert texts == ["Echo", "foxtrot"]


def test_dedup_tolerance_boundary_exactly_at_tolerance_dedupes() -> None:
    """Boundary-exact (<=): all values are exact binary fractions so the
    comparison is genuinely AT the tolerance, not one ulp off."""
    merger = StreamingChunkMerger(overlap_s=1.0, dedup_tolerance_s=0.5)
    merger.add_window(window(0, 0.0, 4.0, w("golf", 3.0, 3.5)))  # midpoint 3.25
    # Cut between windows = 3.0 + 0.5 = 3.5; midpoint 3.75, diff == 0.5 exactly.
    merger.add_window(window(1, 3.0, 7.0, w("golf", 3.5, 4.0)))
    assert [t.text for t in merger.flush()] == ["golf"]


def test_dedup_tolerance_boundary_just_over_keeps_both_words() -> None:
    """Just over tolerance: genuinely two utterances of the same word."""
    merger = StreamingChunkMerger(overlap_s=1.0, dedup_tolerance_s=0.5)
    merger.add_window(window(0, 0.0, 4.0, w("hotel", 3.0, 3.5)))  # midpoint 3.25
    merger.add_window(window(1, 3.0, 7.0, w("hotel", 3.625, 4.125)))  # diff 0.625 > 0.5
    assert [t.text for t in merger.flush()] == ["hotel", "hotel"]


def test_different_text_straddling_cut_is_never_deduped() -> None:
    merger = StreamingChunkMerger(overlap_s=0.8)
    merger.add_window(window(0, 0.0, 4.0, w("india", 3.3, 3.5)))
    merger.add_window(window(1, 3.2, 7.2, w("juliet", 3.5, 3.8)))
    assert [t.text for t in merger.flush()] == ["india", "juliet"]


def test_three_window_chain_owns_every_region_exactly_once() -> None:
    """Stateful run over three windows: every overlap resolved, order kept."""
    merger = StreamingChunkMerger(overlap_s=0.8)
    merger.add_window(window(0, 0.0, 4.0, w("one", 0.5, 0.8), w("two", 3.5, 3.9)))
    merger.add_window(window(1, 3.2, 7.2, w("two", 3.55, 3.95), w("three", 5.0, 5.4)))
    merger.add_window(window(2, 6.4, 10.4, w("four", 7.0, 7.4), w("five", 9.0, 9.4)))
    assert [t.text for t in merger.flush()] == ["one", "two", "three", "four", "five"]


def test_partial_snapshot_shows_tentative_tail_which_the_next_window_may_revise() -> None:
    """merged_words() includes the tentative tail; a later window that
    re-heard that region REPLACES it (later-window-wins policy) — partials
    are revisable, finals are the settled truth."""
    merger = StreamingChunkMerger(overlap_s=0.8)
    merger.add_window(window(0, 0.0, 4.0, w("kilo", 1.0, 1.3), w("lima", 3.7, 3.95)))
    snapshot_after_first = [t.text for t in merger.merged_words()]
    assert snapshot_after_first == ["kilo", "lima"]  # committed + tentative tail
    # Window 1 re-heard [3.2, 7.2] and reported only "mike": the tentative
    # "lima" (midpoint 3.825 >= cut 3.6) is revised away, deterministically.
    merger.add_window(window(1, 3.2, 7.2, w("mike", 4.5, 4.8)))
    assert [t.text for t in merger.flush()] == ["kilo", "mike"]


def test_replaying_an_already_consumed_window_index_fails_closed() -> None:
    merger = StreamingChunkMerger(overlap_s=0.8)
    merger.add_window(window(0, 0.0, 4.0, w("november", 1.0, 1.2)))
    with pytest.raises(ValueError, match="already received"):
        merger.add_window(window(0, 0.0, 4.0, w("november", 1.0, 1.2)))


def test_duplicate_buffered_index_fails_closed_before_processing() -> None:
    merger = StreamingChunkMerger(overlap_s=0.8)
    merger.add_window(window(2, 6.4, 10.4, w("oscar", 7.0, 7.2)))  # buffered (waiting for 0)
    with pytest.raises(ValueError, match="already received"):
        merger.add_window(window(2, 6.4, 10.4, w("oscar", 7.0, 7.2)))


def test_flush_resets_state_for_a_new_segment() -> None:
    merger = StreamingChunkMerger(overlap_s=0.8)
    merger.add_window(window(0, 0.0, 4.0, w("papa", 1.0, 1.2)))
    assert [t.text for t in merger.flush()] == ["papa"]
    # A fresh segment restarts at index 0 without complaint.
    merger.add_window(window(0, 10.0, 14.0, w("quebec", 11.0, 11.2)))
    assert [t.text for t in merger.flush()] == ["quebec"]


def test_invalid_word_timestamps_are_rejected_at_construction() -> None:
    with pytest.raises(ValueError, match="non-finite"):
        w("bad", float("nan"), 1.0)
    with pytest.raises(ValueError, match="t_end < t_start"):
        w("bad", 2.0, 1.0)
    with pytest.raises(ValueError, match="non-finite"):
        window(0, float("inf"), 4.0)
