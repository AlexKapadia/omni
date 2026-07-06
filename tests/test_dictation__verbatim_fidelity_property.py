"""Property sweep (seeded): dictated text is NEVER rewritten anywhere.

The fidelity mandate is binding: the transcript is ground truth. This
sweep generates thousands of adversarial texts (unicode, punctuation
storms, wake-word lookalikes, injection-flavoured strings) and proves the
two verbatim properties hold for every one of them:

1. Mode split: a COMMAND body is an exact contiguous suffix of the input
   (front-trim only); NOTE mode implies the caller's original string is
   the artifact (the splitter returns no body at all).
2. Session text assembly: joining word tokens never alters a token.

Seeded PRNG (deterministic, reproducible) — property-based in spirit; the
repo has no hypothesis dependency by design.
"""

import random
import string

from engine.dictation.dictation_mode_splitter import (
    DictationMode,
    split_dictation_mode,
)
from engine.dictation.dictation_session_service import words_to_verbatim_text
from engine.stt.word_token_types import WordToken

_SEED = 20260706
_CASES = 3000

_ALPHABETS = [
    string.ascii_letters,
    string.ascii_letters + string.digits + " ,.:;!?-—–…'\"()[]",  # noqa: RUF001 — en dash deliberate
    "äöüßéèêñáíóúç ",  # accented latin
    "日本語のメモ 中文笔记 ",  # CJK
    "😀🎉🚀📅 ",  # emoji
    " \t",  # whitespace runs
]

_WAKE_PREFIXES = [
    "Omni, ",
    "omni ",
    "OMNI: ",
    "Ómni, ",
    "  omni — ",
    "omnibus ",  # NOT a wake word
    "omni-channel ",  # NOT a wake word (hyphenated)
    "",
]


def _random_text(rng: random.Random) -> str:
    prefix = rng.choice(_WAKE_PREFIXES)
    alphabet = rng.choice(_ALPHABETS)
    body = "".join(rng.choice(alphabet) for _ in range(rng.randint(0, 60)))
    return prefix + body


def test_command_body_is_always_an_exact_suffix() -> None:
    rng = random.Random(_SEED)
    for _ in range(_CASES):
        text = _random_text(rng)
        split = split_dictation_mode(text)
        if split.mode is DictationMode.COMMAND:
            # Front-trim only: the body appears verbatim at the END of the
            # input. Any rewrite (case fold, accent strip, normalisation
            # leaking out of the comparison) breaks this immediately.
            assert text.endswith(split.command_body), (
                f"body {split.command_body!r} is not a suffix of {text!r}"
            )
        else:
            assert split.command_body == ""


def test_splitting_is_deterministic() -> None:
    rng = random.Random(_SEED + 1)
    texts = [_random_text(rng) for _ in range(500)]
    first = [split_dictation_mode(t) for t in texts]
    second = [split_dictation_mode(t) for t in texts]
    assert first == second


def test_word_join_never_alters_a_token() -> None:
    rng = random.Random(_SEED + 2)
    for _ in range(_CASES):
        token_count = rng.randint(0, 20)
        words: list[WordToken] = []
        t = 0.0
        for _n in range(token_count):
            alphabet = rng.choice(_ALPHABETS).replace(" ", "").replace("\t", "") or "x"
            token_text = "".join(rng.choice(alphabet) for _ in range(rng.randint(1, 12)))
            words.append(WordToken(token_text, t, t + 0.1))
            t += 0.2
        joined = words_to_verbatim_text(words)
        # Every token appears verbatim, in order, separated by single spaces.
        assert joined == " ".join(w.text for w in words)


def test_word_join_strips_tokenizer_edge_spaces_only() -> None:
    """Guard rail on the ONE permitted normalisation: token-edge whitespace
    (a tokenizer artifact) may be trimmed; interior characters never."""
    words = [WordToken(" hello ", 0.0, 0.1), WordToken("wörld…", 0.2, 0.3)]
    assert words_to_verbatim_text(words) == "hello wörld…"
    # Interior punctuation/space is untouched.
    assert words_to_verbatim_text([WordToken("don't", 0.0, 0.1)]) == "don't"


def test_empty_and_whitespace_tokens_yield_empty_text() -> None:
    assert words_to_verbatim_text([]) == ""
    assert words_to_verbatim_text([WordToken("  ", 0.0, 0.1)]) == ""
