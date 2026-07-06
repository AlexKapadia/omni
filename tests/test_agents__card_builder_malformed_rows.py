"""Card-builder robustness: malformed source rows are skipped, never crash.

Invariants under test: extraction payloads and dictation intent fields are
UNTRUSTED model output — every malformed shape in the table below must be
skipped with an honest reason while valid siblings still become cards;
re-running is idempotent (no duplicate cards); the confidence floor and
the 'unknown' intent are deny-by-default.
"""

import json
from pathlib import Path

import aiosqlite
import pytest

from engine.agents.approval_card_builder import build_cards_from_extraction
from engine.agents.approval_cards_repository import list_cards
from engine.agents.dictation_intent_card_builder import build_card_from_dictation_intent
from engine.dictation.dictation_intents_repository import DictationIntentRecord
from tests.agents_test_support import TS, insert_meeting, migrated_connection


async def _built_extraction(
    conn: aiosqlite.Connection, payload: object, row_id: int = 1
) -> tuple[int, int]:
    """(created, skipped) counts for one extraction payload."""
    result = await build_cards_from_extraction(
        conn,
        meeting_id="m-1",
        extraction_row_id=row_id,
        payload_json=payload if isinstance(payload, str) else json.dumps(payload),
        created_at=TS,
    )
    return len(result.created_card_ids), len(result.skipped)


@pytest.mark.parametrize(
    ("payload", "expect_created", "expect_skipped_at_least"),
    [
        ("not json at all {{{", 0, 1),
        ("[1, 2, 3]", 0, 1),  # JSON but not an object
        ('"just a string"', 0, 1),
        ({"contacts": "not-a-list", "dates": 17}, 0, 0),  # wrong types -> no items
        ({"contacts": [42, None, "str"]}, 0, 3),  # non-object items
        ({"contacts": [{"name": ""}]}, 0, 1),  # empty name
        ({"contacts": [{"name": "   "}]}, 0, 1),  # whitespace name
        ({"contacts": [{"name": 123}]}, 0, 1),  # numeric name refused, not coerced
        ({"dates": [{"when": "Friday"}]}, 0, 1),  # missing what
        ({"dates": [{"what": "Review"}]}, 0, 1),  # missing when
        # One good contact among garbage: the good one still lands.
        ({"contacts": [{"name": 1}, {"name": "Elena Fischer", "email": "e@nw.io"}]}, 1, 1),
        # Good date + good contact -> two cards.
        (
            {
                "contacts": [{"name": "Marcus Ito"}],
                "dates": [{"when": "next Tuesday 10:00", "what": "Contract review"}],
            },
            2,
            0,
        ),
    ],
)
async def test_extraction_malformed_row_table(
    tmp_db_path: Path,
    real_migrations_dir: Path,
    payload: object,
    expect_created: int,
    expect_skipped_at_least: int,
) -> None:
    conn = await migrated_connection(tmp_db_path, real_migrations_dir)
    try:
        await insert_meeting(conn)
        created, skipped = await _built_extraction(conn, payload)
        assert created == expect_created
        assert skipped >= expect_skipped_at_least
        assert len(await list_cards(conn)) == expect_created
    finally:
        await conn.close()


async def test_extraction_oversized_fields_are_bounded_not_crashing(
    tmp_db_path: Path, real_migrations_dir: Path
) -> None:
    """A 100k-char name must not produce a 100k-char card (bounds hold)."""
    conn = await migrated_connection(tmp_db_path, real_migrations_dir)
    try:
        await insert_meeting(conn)
        created, _ = await _built_extraction(
            conn, {"contacts": [{"name": "N" * 100_000, "email": "e@x.io"}]}
        )
        assert created == 1
        card = (await list_cards(conn))[0]
        assert len(json.loads(card.payload_json)["name"]) == 200  # _clean_str cap
    finally:
        await conn.close()


async def test_rebuilding_the_same_extraction_row_is_idempotent(
    tmp_db_path: Path, real_migrations_dir: Path
) -> None:
    conn = await migrated_connection(tmp_db_path, real_migrations_dir)
    try:
        await insert_meeting(conn)
        payload = {"contacts": [{"name": "Marcus Ito", "phone": "+44 20 7000 0000"}]}
        first_created, _ = await _built_extraction(conn, payload)
        second_created, second_skipped = await _built_extraction(conn, payload)
        assert first_created == 1
        assert second_created == 0  # duplicate suggestion refused
        assert second_skipped == 1
        assert len(await list_cards(conn)) == 1
    finally:
        await conn.close()


def _intent(
    intent_type: str,
    fields: object,
    *,
    confidence: float = 0.9,
    raw_text: str = "Omni, do the thing",
    row_id: int = 1,
) -> DictationIntentRecord:
    return DictationIntentRecord(
        id=row_id,
        ts=TS,
        raw_text=raw_text,
        intent_type=intent_type,
        fields_json=fields if isinstance(fields, str) else json.dumps(fields),
        confidence=confidence,
        provider="groq",
        model="test",
    )


@pytest.mark.parametrize(
    ("record", "expect_created"),
    [
        # unknown intents NEVER become cards, even at confidence 1.0
        (_intent("unknown", {}, confidence=1.0), 0),
        # below the 0.6 floor: recorded but not suggested (boundary-exact:
        # 0.59 refused, 0.6 accepted — see the boundary test below)
        (_intent("create_event", {"title": "Standup"}, confidence=0.59), 0),
        (_intent("upsert_contact", {}, confidence=0.9), 0),  # no name -> unactionable
        (_intent("upsert_contact", {"name": 42}, confidence=0.9), 0),  # non-str name
        (_intent("create_event", "not json {{{", confidence=0.9), 0),
        (_intent("create_event", '["list"]', confidence=0.9), 0),  # fields not object
        (_intent("create_event", {"title": "Standup", "when": "Friday 1pm"}), 1),
        (_intent("upsert_contact", {"name": "Tom Reed", "email": "tom@reed.io"}), 1),
        (_intent("draft_email", {"to": "tom@reed.io", "subject": "Terms"}), 1),
        (_intent("write_note", {"body": "Remember the demo"}), 1),
        # write_note falls back to the verbatim raw text when fields are bare
        (_intent("write_note", {}), 1),
    ],
)
async def test_dictation_intent_table(
    tmp_db_path: Path,
    real_migrations_dir: Path,
    record: DictationIntentRecord,
    expect_created: int,
) -> None:
    conn = await migrated_connection(tmp_db_path, real_migrations_dir)
    try:
        result = await build_card_from_dictation_intent(conn, record=record, created_at=TS)
        assert len(result.created_card_ids) == expect_created
        if expect_created == 0:
            assert result.skipped  # every refusal carries an honest reason
    finally:
        await conn.close()


async def test_confidence_floor_boundary_is_exact(
    tmp_db_path: Path, real_migrations_dir: Path
) -> None:
    """0.6 is IN (>= floor), 0.5999... is OUT — boundary-exact, on/just-under."""
    conn = await migrated_connection(tmp_db_path, real_migrations_dir)
    try:
        at_floor = _intent("write_note", {"body": "x"}, confidence=0.6, row_id=1)
        just_under = _intent("write_note", {"body": "x"}, confidence=0.5999999, row_id=2)
        result_at = await build_card_from_dictation_intent(conn, record=at_floor, created_at=TS)
        result_under = await build_card_from_dictation_intent(
            conn, record=just_under, created_at=TS
        )
        assert len(result_at.created_card_ids) == 1
        assert len(result_under.created_card_ids) == 0
    finally:
        await conn.close()


async def test_dictation_cards_carry_no_meeting_and_provenance_points_at_the_row(
    tmp_db_path: Path, real_migrations_dir: Path
) -> None:
    conn = await migrated_connection(tmp_db_path, real_migrations_dir)
    try:
        record = _intent("upsert_contact", {"name": "Ana Cruz"}, row_id=77)
        await build_card_from_dictation_intent(conn, record=record, created_at=TS)
        card = (await list_cards(conn))[0]
        assert card.meeting_id is None
        assert card.source == "dictation"
        assert card.source_row_id == 77
        assert card.status == "pending"  # born pending, always
    finally:
        await conn.close()
