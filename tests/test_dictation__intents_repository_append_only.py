"""dictation_intents (0007): schema-level append-only + repository honesty.

Runs the REAL migration files against a throwaway database, then attacks
the table directly: UPDATE and DELETE must be blocked by the schema's own
triggers (defence in depth below the repository), and the CHECK
constraints must reject out-of-enum intents and out-of-range confidence.
"""

import json
import sqlite3
from pathlib import Path
from types import MappingProxyType

import aiosqlite
import pytest

from engine.dictation.dictation_intent_schema import (
    DictationIntentType,
    ParsedIntent,
    unknown_intent,
)
from engine.dictation.dictation_intents_repository import (
    insert_dictation_intent,
    list_dictation_intents,
)
from engine.storage.sqlite_connection import open_sqlite_connection
from engine.storage.sqlite_migrations_runner import apply_migrations


async def _migrated_connection(
    tmp_db_path: Path, real_migrations_dir: Path
) -> aiosqlite.Connection:
    await apply_migrations(tmp_db_path, real_migrations_dir)
    return await open_sqlite_connection(tmp_db_path)


def _intent(fields: dict[str, object] | None = None) -> ParsedIntent:
    return ParsedIntent(
        intent_type=DictationIntentType.CREATE_EVENT,
        fields=MappingProxyType(fields if fields is not None else {"title": "lunch"}),
        confidence=0.87,
    )


async def test_insert_then_read_back_verbatim(
    tmp_db_path: Path, real_migrations_dir: Path
) -> None:
    connection = await _migrated_connection(tmp_db_path, real_migrations_dir)
    try:
        raw = 'Omni, schedule lunch — "Friday" at 1 😀'
        row_id = await insert_dictation_intent(
            connection,
            ts="2026-07-06T12:00:00+00:00",
            raw_text=raw,
            intent=_intent(),
            provider="groq",
            model="llama-3.3-70b-versatile",
        )
        assert row_id >= 1
        rows = await list_dictation_intents(connection)
        assert len(rows) == 1
        record = rows[0]
        assert record.raw_text == raw  # verbatim, unicode intact (fidelity)
        assert record.intent_type == "create_event"
        assert json.loads(record.fields_json) == {"title": "lunch"}
        assert record.confidence == 0.87
        assert record.provider == "groq"
    finally:
        await connection.close()


async def test_unknown_intent_with_null_provider_is_recordable(
    tmp_db_path: Path, real_migrations_dir: Path
) -> None:
    """Router-down path: the utterance is still recorded, honestly unknown."""
    connection = await _migrated_connection(tmp_db_path, real_migrations_dir)
    try:
        await insert_dictation_intent(
            connection,
            ts="2026-07-06T12:00:00+00:00",
            raw_text="Omni, do the thing",
            intent=unknown_intent("router unavailable: all providers failed"),
            provider=None,
            model=None,
        )
        record = (await list_dictation_intents(connection))[0]
        assert record.intent_type == "unknown"
        assert record.confidence == 0.0
        assert record.provider is None and record.model is None
    finally:
        await connection.close()


async def test_update_is_blocked_by_the_schema_itself(
    tmp_db_path: Path, real_migrations_dir: Path
) -> None:
    connection = await _migrated_connection(tmp_db_path, real_migrations_dir)
    try:
        await insert_dictation_intent(
            connection,
            ts="t",
            raw_text="Omni, x",
            intent=_intent(),
            provider=None,
            model=None,
        )
        with pytest.raises(sqlite3.DatabaseError, match="append-only"):
            # Bypass the repository entirely: the SCHEMA must refuse.
            await connection.execute("UPDATE dictation_intents SET raw_text = 'forged'")
        record = (await list_dictation_intents(connection))[0]
        assert record.raw_text == "Omni, x"  # untouched after the blocked attack
    finally:
        await connection.close()


async def test_delete_is_blocked_by_the_schema_itself(
    tmp_db_path: Path, real_migrations_dir: Path
) -> None:
    connection = await _migrated_connection(tmp_db_path, real_migrations_dir)
    try:
        await insert_dictation_intent(
            connection,
            ts="t",
            raw_text="Omni, x",
            intent=_intent(),
            provider=None,
            model=None,
        )
        with pytest.raises(sqlite3.DatabaseError, match="append-only"):
            await connection.execute("DELETE FROM dictation_intents")
        assert len(await list_dictation_intents(connection)) == 1
    finally:
        await connection.close()


@pytest.mark.parametrize(
    ("column_override", "value"),
    [
        ("intent_type", "execute_arbitrary_code"),  # out-of-enum intent
        ("confidence", 1.5),  # just over the ceiling
        ("confidence", -0.5),  # just under the floor
    ],
)
async def test_check_constraints_reject_bad_rows(
    tmp_db_path: Path,
    real_migrations_dir: Path,
    column_override: str,
    value: object,
) -> None:
    connection = await _migrated_connection(tmp_db_path, real_migrations_dir)
    try:
        row: dict[str, object] = {
            "ts": "t",
            "raw_text": "x",
            "intent_type": "unknown",
            "fields_json": "{}",
            "confidence": 0.5,
        }
        row[column_override] = value
        with pytest.raises(sqlite3.DatabaseError):
            await connection.execute(
                "INSERT INTO dictation_intents"
                " (ts, raw_text, intent_type, fields_json, confidence)"
                " VALUES (:ts, :raw_text, :intent_type, :fields_json, :confidence)",
                row,
            )
    finally:
        await connection.close()


async def test_list_returns_newest_first(
    tmp_db_path: Path, real_migrations_dir: Path
) -> None:
    connection = await _migrated_connection(tmp_db_path, real_migrations_dir)
    try:
        for n in range(3):
            await insert_dictation_intent(
                connection,
                ts=f"2026-07-06T12:00:0{n}+00:00",
                raw_text=f"Omni, item {n}",
                intent=_intent(),
                provider=None,
                model=None,
            )
        rows = await list_dictation_intents(connection)
        assert [r.raw_text for r in rows] == ["Omni, item 2", "Omni, item 1", "Omni, item 0"]
    finally:
        await connection.close()
