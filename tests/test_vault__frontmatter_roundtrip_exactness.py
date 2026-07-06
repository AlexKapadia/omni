"""Frontmatter codec: emit -> parse round-trips EXACTLY; bad input fails closed.

The codec is hand-rolled (no PyYAML) for a narrow schema: string scalars,
booleans, flat string lists. These tests prove hostile values (colons,
quotes, backslashes, YAML-ambiguous words, numerics) survive a round trip
byte-for-value, and that anything outside the schema is refused.
"""

import random

import pytest

from engine.vault.frontmatter_codec import (
    FrontmatterValue,
    emit_frontmatter,
    emit_scalar,
    parse_frontmatter,
    parse_scalar,
)
from engine.vault.vault_errors import FrontmatterFormatError

_HOSTILE_STRINGS = [
    "plain title",
    "colon: in value",
    'she said "hello"',
    "back\\slash \\\\ double",
    'mix: "quotes" and \\escapes\\',
    "true",
    "false",
    "null",
    "yes",
    "~",
    "123",
    "3.14",
    "-42",
    "1e5",
    "07",
    " leading space",
    "trailing space ",
    "",
    "- looks like a list item",
    "# looks like a comment",
    "[looks, like, flow]",
    "{looks: like, a: map}",
    "*anchor &ref !tag",
    "评审会议 🚀 مرحبا שלום",
    "--- looks like a fence",
    "key_like: value_like: another",
]


@pytest.mark.parametrize("value", _HOSTILE_STRINGS)
def test_scalar_round_trip_is_exact(value: str) -> None:
    assert parse_scalar(emit_scalar(value)) == value


def test_full_frontmatter_round_trip_with_hostile_values() -> None:
    fields: dict[str, FrontmatterValue] = {
        "date": "2026-07-06",
        "title": 'Board sync: "Q3" review \\ recap',
        "attendees": ["Alice O'Hara", "评审: 主持人", "🚀 Bob", "مرحبا"],
        "tags": [],
        "calendar_event_id": "evt_123-abc",
        "disclosed": True,
        "archived": False,
    }
    parsed, body = parse_frontmatter(emit_frontmatter(fields) + "body text\n")
    assert parsed == fields
    assert body == "body text\n"


def test_property_random_field_sets_round_trip_exactly() -> None:
    """Property-style: random schema-valid field sets always round-trip."""
    for seed in range(50):
        rng = random.Random(seed)
        fields: dict[str, FrontmatterValue] = {}
        for i in range(rng.randint(1, 8)):
            kind = rng.choice(["str", "bool", "list"])
            key = f"key_{i}"
            if kind == "str":
                fields[key] = rng.choice(_HOSTILE_STRINGS)
            elif kind == "bool":
                fields[key] = rng.choice([True, False])
            else:
                fields[key] = [
                    rng.choice(_HOSTILE_STRINGS) for _ in range(rng.randint(0, 4))
                ]
        parsed, body = parse_frontmatter(emit_frontmatter(fields))
        assert parsed == fields, f"seed={seed}"
        assert body == ""


def test_none_valued_fields_are_omitted() -> None:
    text = emit_frontmatter({"date": "2026-07-06", "calendar_event_id": None})
    assert "calendar_event_id" not in text
    parsed, _ = parse_frontmatter(text)
    assert parsed == {"date": "2026-07-06"}


def test_quoted_true_stays_string_and_bare_true_stays_bool() -> None:
    """Boundary-exact: the bool/string distinction survives the round trip."""
    parsed, _ = parse_frontmatter(emit_frontmatter({"a": True, "b": "true"}))
    assert parsed["a"] is True
    assert parsed["b"] == "true"


def test_numeric_looking_strings_stay_strings() -> None:
    parsed, _ = parse_frontmatter(emit_frontmatter({"n": "0123", "f": "1e5"}))
    assert parsed == {"n": "0123", "f": "1e5"}


def test_control_characters_in_values_fail_closed() -> None:
    for bad in ("line\nbreak", "tab\there", "bell\x07", "nul\x00"):
        with pytest.raises(FrontmatterFormatError):
            emit_frontmatter({"title": bad})


def test_illegal_keys_fail_closed() -> None:
    for bad_key in ("has space", "colon:key", "9leading", "", "dash-ok:no", "ключ"):
        with pytest.raises(FrontmatterFormatError):
            emit_frontmatter({bad_key: "v"})


def test_unterminated_block_fails_closed() -> None:
    with pytest.raises(FrontmatterFormatError):
        parse_frontmatter("---\nkey: value\nno closing fence\n")


def test_unparseable_lines_fail_closed_never_guessed() -> None:
    for bad_block in (
        "---\n  nested: map\n---\n",
        "---\n- top level list\n---\n",
        "---\nkey: value\nkey: duplicate\n---\n",
        '---\nkey: "unterminated\n---\n',
        '---\nkey: "bad \\x escape"\n---\n',
    ):
        with pytest.raises(FrontmatterFormatError):
            parse_frontmatter(bad_block)


def test_file_without_frontmatter_returns_empty_fields_and_full_body() -> None:
    text = "# Just a heading\nbody\n"
    parsed, body = parse_frontmatter(text)
    assert parsed == {}
    assert body == text


def test_emitted_block_is_lf_only_and_bom_free() -> None:
    text = emit_frontmatter({"date": "2026-07-06", "attendees": ["A", "B"]})
    assert "\r" not in text
    assert not text.startswith("﻿")
    assert text.startswith("---\n")
    assert text.endswith("---\n")
