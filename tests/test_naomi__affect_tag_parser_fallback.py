"""Naomi affect self-tag parser: fail-open to neutral, never leak tag syntax.

Adversarial intent: the tag rides inside MODEL OUTPUT, downstream of untrusted
transcript/document content (§5.6 prompt-injection). The parser must (1) parse
a well-formed tag and strip it, (2) fall open to None (neutral) on anything
malformed, (3) NEVER let tag syntax reach the spoken/displayed text, and (4)
never raise or hang on hostile input. Seeded fuzz hammers the boundaries.
"""

import random

import pytest

from engine.naomi.affect_self_tag_parser import parse_leading_affect_tag


def test_wellformed_tag_is_parsed_and_stripped() -> None:
    affect, text = parse_leading_affect_tag("<<affect v=+0.6 a=0.7>> The date is August 15th.")
    assert affect is not None
    assert affect.valence == pytest.approx(0.6)
    assert affect.arousal == pytest.approx(0.7)
    assert affect.burst_laugh_intensity is None
    assert text == "The date is August 15th."  # tag fully removed


def test_laugh_burst_with_and_without_intensity() -> None:
    affect, _ = parse_leading_affect_tag("<<affect v=0.8 a=0.85 burst=laugh(0.5)>> haha")
    assert affect is not None and affect.burst_laugh_intensity == pytest.approx(0.5)
    affect2, _ = parse_leading_affect_tag("<<affect v=0.8 a=0.85 burst=laugh>> haha")
    assert affect2 is not None and affect2.burst_laugh_intensity == pytest.approx(1.0)


def test_values_are_clamped_into_contract_ranges() -> None:
    affect, _ = parse_leading_affect_tag("<<affect v=9 a=9>> hi")
    assert affect is not None and affect.valence == 1.0 and affect.arousal == 1.0
    affect2, _ = parse_leading_affect_tag("<<affect v=-9 a=-9>> hi")
    assert affect2 is not None and affect2.valence == -1.0 and affect2.arousal == 0.0


def test_missing_tag_falls_open_to_none_and_keeps_text() -> None:
    affect, text = parse_leading_affect_tag("The date is August 15th.")
    assert affect is None
    assert text == "The date is August 15th."


@pytest.mark.parametrize(
    "raw",
    [
        "<<affect >> hello",  # no axes
        "<<affect v=abc a=xyz>> hello",  # non-numeric
        "<<affect v=0.5>> hello",  # arousal missing
        "  <<affect a=0.5>> hello",  # valence missing
    ],
)
def test_malformed_tag_yields_none_but_never_leaks_tag_syntax(raw: str) -> None:
    affect, text = parse_leading_affect_tag(raw)
    assert affect is None
    # The structural "<<affect ...>>" opener must NOT survive into TTS/display.
    assert "<<affect" not in text
    assert ">>" not in text
    assert text.strip() == "hello"


def test_unclosed_tag_is_stripped_to_end_of_line() -> None:
    affect, text = parse_leading_affect_tag("<<affect v=0.5 a=0.5 the rest never closes")
    assert affect is None
    assert "<<affect" not in text  # never speak an unclosed tag opener


def test_non_string_input_fails_closed() -> None:
    affect, text = parse_leading_affect_tag(None)
    assert affect is None and text == ""
    affect2, text2 = parse_leading_affect_tag(12345)
    assert affect2 is None and text2 == ""


def test_hostile_fuzz_never_raises_and_never_leaks_opener() -> None:
    rng = random.Random(7)
    fragments = ["<<affect", ">>", "v=", "a=", "burst=laugh", "0.5", "-9", " ", "x" * 30, "(", ")"]
    for _ in range(4000):
        raw = "".join(rng.choice(fragments) for _ in range(rng.randint(0, 12)))
        affect, text = parse_leading_affect_tag(raw)  # must never raise
        # If a structural opener was present at the front, it must be stripped;
        # the parser guarantees no "<<affect" survives when it matched one.
        assert isinstance(text, str)
        if affect is not None:
            assert -1.0 <= affect.valence <= 1.0
            assert 0.0 <= affect.arousal <= 1.0
