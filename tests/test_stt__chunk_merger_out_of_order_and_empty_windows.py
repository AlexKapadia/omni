"""Chunk-merger robustness: out-of-order arrival, empty windows, gaps, unicode.

Transcriptions finish out of order (GPU scheduling) and windows can be
empty (silence padding) or missing entirely (a failed transcription =
gap). The merger must stay deterministic through all of it, and unicode
token text must survive byte-identical.
"""

from engine.stt.streaming_chunk_merger import StreamingChunkMerger
from engine.stt.word_token_types import TranscribedWindow, WordToken


def w(text: str, t_start: float, t_end: float) -> WordToken:
    return WordToken(text=text, t_start=t_start, t_end=t_end)


def window(index: int, t_start: float, t_end: float, *words: WordToken) -> TranscribedWindow:
    return TranscribedWindow(index=index, t_start=t_start, t_end=t_end, words=tuple(words))


def _three_windows() -> list[TranscribedWindow]:
    return [
        window(0, 0.0, 4.0, w("one", 0.5, 0.8), w("two", 3.7, 3.95)),
        window(1, 3.2, 7.2, w("two", 3.72, 3.97), w("three", 5.0, 5.3)),
        window(2, 6.4, 10.4, w("four", 7.0, 7.3)),
    ]


def test_out_of_order_arrival_produces_identical_output_to_in_order() -> None:
    """Every arrival permutation of the same windows merges identically."""
    import itertools

    in_order = StreamingChunkMerger(overlap_s=0.8)
    for win in _three_windows():
        in_order.add_window(win)
    expected = [(t.text, t.t_start, t.t_end) for t in in_order.flush()]
    assert expected  # Sanity: the golden merge is not vacuously empty.

    for permutation in itertools.permutations(_three_windows()):
        merger = StreamingChunkMerger(overlap_s=0.8)
        for win in permutation:
            merger.add_window(win)
        result = [(t.text, t.t_start, t.t_end) for t in merger.flush()]
        assert result == expected, f"order {[x.index for x in permutation]} diverged"


def test_out_of_order_windows_do_not_emit_early_in_partial_snapshots() -> None:
    """Window 1 buffered ahead of window 0 must not leak into merged_words."""
    merger = StreamingChunkMerger(overlap_s=0.8)
    merger.add_window(window(1, 3.2, 7.2, w("later", 5.0, 5.3)))
    assert merger.merged_words() == []  # Still waiting for window 0.
    merger.add_window(window(0, 0.0, 4.0, w("sooner", 1.0, 1.3)))
    assert [t.text for t in merger.merged_words()] == ["sooner", "later"]


def test_empty_first_window_yields_no_words_but_advances_the_chain() -> None:
    merger = StreamingChunkMerger(overlap_s=0.8)
    merger.add_window(window(0, 0.0, 4.0))  # Model heard nothing.
    assert merger.merged_words() == []
    merger.add_window(window(1, 3.2, 7.2, w("speech", 4.0, 4.3)))
    assert [t.text for t in merger.flush()] == ["speech"]


def test_empty_middle_window_revises_away_the_disputed_tentative_tail() -> None:
    """Later-window-wins holds even when the later window heard silence:
    the tentative word in the shared overlap is dropped, committed words
    before the cut survive."""
    merger = StreamingChunkMerger(overlap_s=0.8)
    merger.add_window(window(0, 0.0, 4.0, w("kept", 1.0, 1.3), w("disputed", 3.7, 3.95)))
    merger.add_window(window(1, 3.2, 7.2))  # Empty: disputes [3.6, ...] with silence.
    assert [t.text for t in merger.flush()] == ["kept"]


def test_all_empty_windows_flush_to_an_empty_segment() -> None:
    merger = StreamingChunkMerger(overlap_s=0.8)
    for i, t0 in enumerate((0.0, 3.2, 6.4)):
        merger.add_window(window(i, t0, t0 + 4.0))
    assert merger.flush() == []


def test_missing_window_index_is_a_gap_processed_on_flush() -> None:
    """Window 1 never arrives (failed transcription): flush must still
    process buffered window 2 — the gap is absent audio, not a deadlock."""
    merger = StreamingChunkMerger(overlap_s=0.8)
    merger.add_window(window(0, 0.0, 4.0, w("start", 1.0, 1.3)))
    merger.add_window(window(2, 6.4, 10.4, w("end", 7.0, 7.3)))
    assert [t.text for t in merger.merged_words()] == ["start"]  # 2 still buffered.
    assert [t.text for t in merger.flush()] == ["start", "end"]


def test_unicode_token_text_survives_byte_identical() -> None:
    """Accents, CJK, emoji, RTL, combining marks — never normalised/mangled."""
    tokens = ["naïve", "東京", "🎙️", "شكراً", "étude", "Ω≈ç√"]
    merger = StreamingChunkMerger(overlap_s=0.8)
    words = [w(text, 0.2 + i * 0.5, 0.4 + i * 0.5) for i, text in enumerate(tokens)]
    merger.add_window(window(0, 0.0, 4.0, *words))
    merged = merger.flush()
    assert [t.text for t in merged] == tokens
    # Byte-identical, not just str-equal after normalisation:
    for got, expected in zip(merged, tokens, strict=True):
        assert got.text.encode("utf-8") == expected.encode("utf-8")


def test_casefold_dedup_still_respects_unicode_distinctions() -> None:
    """Different unicode words near the cut must never be merged as 'dupes'."""
    merger = StreamingChunkMerger(overlap_s=0.8)
    merger.add_window(window(0, 0.0, 4.0, w("café", 3.3, 3.5)))
    merger.add_window(window(1, 3.2, 7.2, w("cafe", 3.5, 3.8)))  # NOT the same word.
    assert [t.text for t in merger.flush()] == ["café", "cafe"]
