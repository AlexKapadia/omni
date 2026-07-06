"""Window assembler: exact 4 s / 3.2 s-hop geometry, tails, chunk invariance.

Uses ``np.arange`` sample values so every window's CONTENT identifies its
exact sample range — off-by-one boundaries cannot hide.
"""

import numpy as np
import pytest

from engine.stt.streaming_window_assembler import StreamingWindowAssembler

RATE = 16_000
WINDOW_N = 64_000  # 4.0 s
HOP_N = 51_200  # 3.2 s


def _ramp(start: int, count: int) -> np.ndarray:
    """Samples whose VALUE equals their absolute index (identity check)."""
    return np.arange(start, start + count, dtype=np.float32)


def test_ten_seconds_yields_windows_at_exact_hop_positions() -> None:
    assembler = StreamingWindowAssembler()
    assembler.open(t_open_s=10.0)
    windows = assembler.feed(_ramp(0, 10 * RATE))
    assert [w.index for w in windows] == [0, 1]
    # Window 0: samples [0, 64000) at t = 10.0.
    assert windows[0].t_start == pytest.approx(10.0)
    np.testing.assert_array_equal(windows[0].samples, _ramp(0, WINDOW_N))
    # Window 1: samples [51200, 115200) at t = 13.2 — 0.8 s overlap with 0.
    assert windows[1].t_start == pytest.approx(13.2)
    np.testing.assert_array_equal(windows[1].samples, _ramp(HOP_N, WINDOW_N))
    # Overlap content is literally shared: last 0.8 s of w0 == first 0.8 s of w1.
    overlap_n = WINDOW_N - HOP_N
    np.testing.assert_array_equal(windows[0].samples[-overlap_n:], windows[1].samples[:overlap_n])
    # Close: tail from hop 2 (102400) to end (160000) = 3.6 s.
    tail = assembler.close()
    assert tail is not None
    assert tail.index == 2
    assert tail.t_start == pytest.approx(10.0 + 2 * 3.2)
    np.testing.assert_array_equal(tail.samples, _ramp(2 * HOP_N, 10 * RATE - 2 * HOP_N))


def test_exactly_one_window_of_audio_emits_it_and_no_tail() -> None:
    """160000... no — 64000 samples: window 0 emits, close has nothing new."""
    assembler = StreamingWindowAssembler()
    assembler.open(0.0)
    windows = assembler.feed(_ramp(0, WINDOW_N))
    assert len(windows) == 1
    # Remaining uncovered audio [51200, 64000) = 0.8 s -> a real tail window.
    tail = assembler.close()
    assert tail is not None
    np.testing.assert_array_equal(tail.samples, _ramp(HOP_N, WINDOW_N - HOP_N))


def test_one_sample_short_of_a_window_defers_to_the_tail() -> None:
    """Boundary-exact: 63999 samples emit nothing; close returns them all."""
    assembler = StreamingWindowAssembler()
    assembler.open(0.0)
    assert assembler.feed(_ramp(0, WINDOW_N - 1)) == []
    tail = assembler.close()
    assert tail is not None
    assert tail.index == 0
    assert tail.samples.size == WINDOW_N - 1


def test_short_utterance_under_four_seconds_arrives_only_via_close() -> None:
    assembler = StreamingWindowAssembler()
    assembler.open(2.5)
    assert assembler.feed(_ramp(0, RATE)) == []  # 1 s: no full window.
    tail = assembler.close()
    assert tail is not None
    assert tail.index == 0
    assert tail.t_start == pytest.approx(2.5)
    np.testing.assert_array_equal(tail.samples, _ramp(0, RATE))


def test_sub_50ms_tail_is_skipped_but_49ms_boundary_is_exact() -> None:
    """A tail under 800 samples (50 ms) is not worth a model call."""
    assembler = StreamingWindowAssembler()
    assembler.open(0.0)
    assembler.feed(_ramp(0, 799))
    assert assembler.close() is None  # 799 < 800: skipped.

    assembler.open(0.0)
    assembler.feed(_ramp(0, 800))
    tail = assembler.close()  # Exactly 800: emitted.
    assert tail is not None and tail.samples.size == 800


def test_chunked_feeding_produces_identical_windows_to_one_shot() -> None:
    """Metamorphic invariance: odd-sized chunk feeding == single feed."""
    rng = np.random.default_rng(7)
    total = int(9.7 * RATE)
    one_shot = StreamingWindowAssembler()
    one_shot.open(1.0)
    reference = one_shot.feed(_ramp(0, total))
    reference_tail = one_shot.close()

    chunked = StreamingWindowAssembler()
    chunked.open(1.0)
    collected = []
    position = 0
    while position < total:
        size = int(rng.integers(1, 5000))
        collected.extend(chunked.feed(_ramp(position, min(size, total - position))))
        position += size
    chunked_tail = chunked.close()

    assert len(collected) == len(reference)
    for got, expected in zip(collected, reference, strict=True):
        assert got.index == expected.index
        assert got.t_start == expected.t_start
        np.testing.assert_array_equal(got.samples, expected.samples)
    assert reference_tail is not None and chunked_tail is not None
    np.testing.assert_array_equal(chunked_tail.samples, reference_tail.samples)


def test_window_times_stay_exact_over_a_long_segment_no_float_drift() -> None:
    """30 windows deep, t_start must still be EXACT (integer sample math)."""
    assembler = StreamingWindowAssembler()
    assembler.open(0.0)
    windows = assembler.feed(np.zeros(HOP_N * 30 + WINDOW_N, dtype=np.float32))
    assert len(windows) == 31
    for k, win in enumerate(windows):
        assert win.t_start == k * HOP_N / RATE  # Exact equality, not approx.


def test_lifecycle_errors_fail_closed() -> None:
    assembler = StreamingWindowAssembler()
    with pytest.raises(RuntimeError, match="no open segment"):
        assembler.feed(np.zeros(10, dtype=np.float32))
    with pytest.raises(RuntimeError, match="no open segment"):
        assembler.close()
    assembler.open(0.0)
    with pytest.raises(RuntimeError, match="already has an open segment"):
        assembler.open(1.0)
    with pytest.raises(ValueError, match="hop"):
        StreamingWindowAssembler(window_s=1.0, hop_s=2.0)


def test_reopen_after_close_starts_a_fresh_segment() -> None:
    assembler = StreamingWindowAssembler()
    assembler.open(0.0)
    assembler.feed(_ramp(0, RATE))
    assembler.close()
    assembler.open(50.0)
    tail = assembler.feed(_ramp(0, RATE))
    assert tail == []
    final = assembler.close()
    assert final is not None
    assert final.index == 0
    assert final.t_start == pytest.approx(50.0)  # No bleed from the old segment.
