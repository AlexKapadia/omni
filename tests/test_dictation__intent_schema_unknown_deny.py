"""Intent completion parsing: strict schema, unknown-deny on ANY deviation.

The model's output is untrusted input feeding approval cards, so the
validator must fail closed: malformed, hostile, or out-of-shape output
degrades to the ``unknown`` intent (recorded, never actionable) — never a
coerced object, never an exception.
"""

import json

import pytest

from engine.dictation.dictation_intent_schema import (
    DICTATION_INTENT_JSON_SCHEMA,
    DictationIntentType,
    parse_intent_completion_text,
    unknown_intent,
)


def _valid(intent_type: str = "create_event", confidence: float = 0.9) -> str:
    return json.dumps(
        {
            "intent_type": intent_type,
            "fields": {"title": "lunch with Tom", "date": "Friday", "time": "13:00"},
            "confidence": confidence,
        }
    )


def test_valid_completion_parses_exactly() -> None:
    parsed = parse_intent_completion_text(_valid())
    assert parsed.intent_type is DictationIntentType.CREATE_EVENT
    assert dict(parsed.fields) == {"title": "lunch with Tom", "date": "Friday", "time": "13:00"}
    assert parsed.confidence == 0.9
    assert parsed.parse_error == ""


@pytest.mark.parametrize("intent", [i.value for i in DictationIntentType])
def test_every_declared_intent_type_round_trips(intent: str) -> None:
    assert parse_intent_completion_text(_valid(intent)).intent_type.value == intent


def test_fenced_json_is_unwrapped_then_strictly_validated() -> None:
    fenced = f"```json\n{_valid('draft_email')}\n```"
    assert parse_intent_completion_text(fenced).intent_type is DictationIntentType.DRAFT_EMAIL


@pytest.mark.parametrize(
    "text",
    [
        "",  # empty
        "not json at all",
        "null",
        "[]",  # array, not object
        '"create_event"',  # bare string
        "{}",  # missing all keys
        '{"intent_type": "create_event", "fields": {}}',  # missing confidence
        _valid()[:-5],  # truncated JSON
        # extra key smuggled in (additionalProperties: false)
        json.dumps(
            {"intent_type": "create_event", "fields": {}, "confidence": 0.5, "execute": True}
        ),
        # unknown enum value — a made-up privileged intent must not pass
        json.dumps({"intent_type": "delete_all_files", "fields": {}, "confidence": 1.0}),
        json.dumps({"intent_type": "CREATE_EVENT", "fields": {}, "confidence": 1.0}),  # wrong case
        json.dumps({"intent_type": 7, "fields": {}, "confidence": 0.5}),  # wrong type
        json.dumps({"intent_type": "create_event", "fields": [], "confidence": 0.5}),  # fields list
        json.dumps({"intent_type": "create_event", "fields": "x", "confidence": 0.5}),
        json.dumps({"intent_type": "create_event", "fields": {}, "confidence": "high"}),
        json.dumps({"intent_type": "create_event", "fields": {}, "confidence": True}),  # bool
        json.dumps({"intent_type": "create_event", "fields": {}, "confidence": 1.01}),  # > 1
        json.dumps({"intent_type": "create_event", "fields": {}, "confidence": -0.01}),  # < 0
        json.dumps({"intent_type": "create_event", "fields": {}, "confidence": None}),
        # prompt-injection flavoured free text around valid-looking JSON
        f"Sure! Here is the intent you asked for: {_valid()}",
    ],
)
def test_any_deviation_degrades_to_unknown(text: str) -> None:
    parsed = parse_intent_completion_text(text)
    assert parsed.intent_type is DictationIntentType.UNKNOWN
    assert parsed.confidence == 0.0
    assert dict(parsed.fields) == {}
    assert parsed.parse_error != ""  # honest reason, never silent


@pytest.mark.parametrize("boundary", [0.0, 1.0])
def test_confidence_boundaries_inclusive(boundary: float) -> None:
    """On-the-line values are valid; just-over/under are rejected above."""
    parsed = parse_intent_completion_text(_valid(confidence=boundary))
    assert parsed.confidence == boundary
    assert parsed.intent_type is DictationIntentType.CREATE_EVENT


def test_unknown_intent_serialises_empty_fields() -> None:
    assert unknown_intent("why").fields_as_json() == "{}"


def test_schema_enum_matches_the_db_check_constraint_values() -> None:
    """The schema sent to providers and the 0007 CHECK constraint must agree
    — a drift would let a 'valid' parse fail to persist (or vice versa)."""
    properties = DICTATION_INTENT_JSON_SCHEMA["properties"]
    assert isinstance(properties, dict)
    enum_values = properties["intent_type"]["enum"]
    assert enum_values == [
        "create_event",
        "upsert_contact",
        "draft_email",
        "write_note",
        "unknown",
    ]
