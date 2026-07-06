"""FIDELITY property tests: the merger never invents or rewrites a token.

Binding user mandate: the raw transcript is ground truth. These
property-style tests (seeded randomness, hundreds of generated segments)
prove the merger can only SELECT and ORDER tokens — every output token is
one of the exact input token objects, output order is monotonic in time,
and output size never exceeds input size.
"""

import random
import string

from engine.stt.streaming_chunk_merger import StreamingChunkMerger
from engine.stt.word_token_types import TranscribedWindow, WordToken

# Alphabet deliberately hostile: ascii, unicode letters, emoji, punctuation.
_VOCAB_CHARS = string.ascii_letters + "àéîõü東京日本語🎙️😀'’-,."  # noqa: RUF001 — curly quote is intentional hostile input


def _random_word(rng: random.Random) -> str:
    return "".join(rng.choice(_VOCAB_CHARS) for _ in range(rng.randint(1, 12)))


def _random_segment_windows(rng: random.Random) -> list[TranscribedWindow]:
    """Generate a realistic hop-chained segment with random words."""
    window_s, hop_s = 4.0, 3.2
    count = rng.randint(1, 6)
    windows: list[TranscribedWindow] = []
    for index in range(count):
        t0 = index * hop_s
        t1 = t0 + window_s if index < count - 1 else t0 + rng.uniform(0.3, window_s)
        words = []
        for _ in range(rng.randint(0, 10)):
            start = rng.uniform(t0, max(t0, t1 - 0.05))
            end = min(t1, start + rng.uniform(0.05, 0.6))
            words.append(WordToken(text=_random_word(rng), t_start=start, t_end=end))
        windows.append(
            TranscribedWindow(index=index, t_start=t0, t_end=t1, words=tuple(words))
        )
    return windows


def test_every_output_token_is_an_exact_input_token_object() -> None:
    """500 random segments: outputs ⊆ inputs, by OBJECT IDENTITY.

    Identity (not equality) is the strongest possible fidelity proof: the
    merger cannot have rewritten text or timestamps if it returns the very
    objects it was given.
    """
    rng = random.Random(0xF1DE)
    for case in range(500):
        windows = _random_segment_windows(rng)
        input_ids = {id(w) for win in windows for w in win.words}
        merger = StreamingChunkMerger(overlap_s=0.8)
        order = list(windows)
        rng.shuffle(order)  # Out-of-order arrival must not weaken fidelity.
        for win in order:
            merger.add_window(win)
        merged = merger.flush()
        for token in merged:
            assert id(token) in input_ids, f"case {case}: token {token.text!r} was fabricated"
        assert len(merged) <= sum(len(win.words) for win in windows), f"case {case}: grew"


def test_partial_snapshots_are_also_exact_input_tokens() -> None:
    """Fidelity holds mid-stream, not just at flush."""
    rng = random.Random(0xBEEF)
    for _ in range(200):
        windows = _random_segment_windows(rng)
        input_ids = {id(w) for win in windows for w in win.words}
        merger = StreamingChunkMerger(overlap_s=0.8)
        for win in windows:
            merger.add_window(win)
            for token in merger.merged_words():
                assert id(token) in input_ids


def test_output_order_is_monotonic_by_midpoint() -> None:
    """The merged sequence reads in time order — no scrambled transcripts."""
    rng = random.Random(0xCAFE)
    for case in range(300):
        merger = StreamingChunkMerger(overlap_s=0.8)
        for win in _random_segment_windows(rng):
            merger.add_window(win)
        merged = merger.flush()
        midpoints = [t.midpoint for t in merged]
        assert midpoints == sorted(midpoints), f"case {case}: out-of-order output"


def test_no_duplicate_token_objects_in_output() -> None:
    """A token can be selected at most once — duplication is fabrication."""
    rng = random.Random(0xD0D0)
    for case in range(300):
        merger = StreamingChunkMerger(overlap_s=0.8)
        for win in _random_segment_windows(rng):
            merger.add_window(win)
        merged = merger.flush()
        identities = [id(t) for t in merged]
        assert len(identities) == len(set(identities)), f"case {case}: object duplicated"


def test_determinism_same_input_same_output_across_many_runs() -> None:
    """Identical segments merge identically on every run (no hidden state)."""
    rng = random.Random(0x5EED)
    windows = _random_segment_windows(rng)
    reference: list[tuple[str, float, float]] | None = None
    for _ in range(50):
        merger = StreamingChunkMerger(overlap_s=0.8)
        for win in windows:
            merger.add_window(win)
        result = [(t.text, t.t_start, t.t_end) for t in merger.flush()]
        if reference is None:
            reference = result
        assert result == reference
