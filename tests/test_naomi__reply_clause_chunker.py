"""Naomi reply clause chunker: verbatim reconstruction + boundedness.

Adversarial intent: the chunks are Cartesia continue:true frames, so their
concatenation MUST equal the reply byte-for-byte (a dropped or reordered
character would make Naomi speak something the UI never showed — a fidelity
violation). Seeded fuzz over messy realistic text asserts join==text and a
bounded chunk count; explicit edge cases cover empty/whitespace/degenerate.
"""

import random

import pytest

from engine.naomi.naomi_reply_clause_chunker import chunk_reply_into_clauses


def test_join_reconstructs_text_exactly_over_seeded_fuzz() -> None:
    rng = random.Random(4242)
    vocab = ["Henderson", "the", "contract", "renewal", "is", "due", "August", "15th", "and", "so"]
    punct = [".", ",", ";", ":", "!", "?", " — ", " ", "\n"]
    for _ in range(3000):
        length = rng.randint(0, 40)
        pieces = []
        for _i in range(length):
            pieces.append(rng.choice(vocab))
            if rng.random() < 0.4:
                pieces.append(rng.choice(punct))
            else:
                pieces.append(" ")
        text = "".join(pieces)
        chunks = chunk_reply_into_clauses(text)
        # THE invariant: concatenation is byte-identical to the input.
        assert "".join(chunks) == text
        # No empty frames (Cartesia continue frames must be non-empty).
        assert all(chunk != "" for chunk in chunks)
        if text and not text.isspace():
            assert len(chunks) >= 1
            # Boundedness: never more chunks than there are characters.
            assert len(chunks) <= len(text)


@pytest.mark.parametrize("text", ["", "   ", "\n\n", "\t "])
def test_empty_or_whitespace_yields_no_chunks(text: str) -> None:
    assert chunk_reply_into_clauses(text) == ()


def test_single_sentence_is_one_or_two_chunks_not_shredded() -> None:
    chunks = chunk_reply_into_clauses("The Henderson contract renewal is due August 15th.")
    assert "".join(chunks) == "The Henderson contract renewal is due August 15th."
    assert 1 <= len(chunks) <= 2  # not shredded into tiny frames


def test_multi_clause_splits_at_boundaries_and_reconstructs() -> None:
    text = "First, we review the terms. Then, if you approve, I draft the email. Done."
    chunks = chunk_reply_into_clauses(text)
    assert "".join(chunks) == text
    assert len(chunks) >= 2  # genuinely streamed, not one giant frame


def test_decimal_and_abbreviation_do_not_split_midtoken() -> None:
    # "3.5" and "e.g." have punctuation NOT followed by whitespace → no split
    # inside them; join must still reconstruct exactly.
    text = "The model is sonic-3.5 and costs e.g. very little to run for one turn now."
    chunks = chunk_reply_into_clauses(text)
    assert "".join(chunks) == text
    assert not any(chunk.strip() in {"3.", "e.", "g."} for chunk in chunks)


def test_long_runon_without_punctuation_still_bounded() -> None:
    text = "word " * 200  # 1000 chars, no clause punctuation at all
    chunks = chunk_reply_into_clauses(text)
    assert "".join(chunks) == text
    # The max-chars force-break keeps a run-on from becoming one frame.
    assert len(chunks) >= 5


def test_tiny_trailing_fragment_is_merged() -> None:
    text = "This is a complete first clause that is long enough. Yes."
    chunks = chunk_reply_into_clauses(text)
    assert "".join(chunks) == text
    # "Yes." (< min_chars) must not be its own two-char continue frame.
    assert chunks[-1].strip() != "Yes."
