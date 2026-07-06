"""Release finalization, COMMAND mode: record the intent, execute NOTHING.

The REAL finalizer runs against a real migrated SQLite file and a real
tmp_path vault, with only the router faked (support in
``tests/dictation_finalization_test_support.py``). Asserts the binding
invariant end to end: command mode only ever RECORDS (no execution path
exists — the strongest proof is that nothing but the intents table is
touched), the persisted raw_text is VERBATIM, and the final result payload
cannot drift after the fact (frozen).
"""

import json
from pathlib import Path

from engine.dictation.dictation_finalization import DictationFinalResult
from engine.dictation.dictation_intent_schema import DictationIntentType
from engine.dictation.dictation_mode_splitter import DictationMode
from tests.dictation_finalization_test_support import (
    FakeRoute,
    make_finalizer,
    read_intents,
)


async def test_command_flow_records_intent_and_never_touches_the_vault(
    tmp_db_path: Path, real_migrations_dir: Path, tmp_path: Path
) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    intent_json = json.dumps(
        {
            "intent_type": "create_event",
            "fields": {"title": "lunch with Tom", "date": "Friday", "time": "13:00"},
            "confidence": 0.92,
        }
    )
    route = FakeRoute({"intent_parsing": intent_json})
    finalizer = make_finalizer(tmp_db_path, real_migrations_dir, vault, route, None)

    verbatim = "Omni, schedule lunch with Tom on Friday at one"
    result = await finalizer.finalize(verbatim)

    assert result.mode is DictationMode.COMMAND
    assert result.text == verbatim
    assert result.intent is not None
    assert result.intent.intent_type is DictationIntentType.CREATE_EVENT
    assert result.intent.confidence == 0.92
    assert result.note_path is None  # commands never write notes
    # The router saw ONLY the command body (wake word stripped), as data.
    assert route.calls == [("intent_parsing", "schedule lunch with Tom on Friday at one")]
    # Persisted append-only with the FULL verbatim text.
    records = await read_intents(tmp_db_path)
    assert len(records) == 1
    record = records[0]
    assert record.raw_text == verbatim  # type: ignore[attr-defined]
    assert record.intent_type == "create_event"  # type: ignore[attr-defined]
    # The vault stayed untouched — recording is the WHOLE write path.
    assert list(vault.iterdir()) == []


async def test_command_with_garbage_model_output_records_unknown(
    tmp_db_path: Path, real_migrations_dir: Path, tmp_path: Path
) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    route = FakeRoute({"intent_parsing": "I cannot help with that."})
    finalizer = make_finalizer(tmp_db_path, real_migrations_dir, vault, route, None)

    result = await finalizer.finalize("Omni, do something ineffable")

    assert result.intent is not None
    assert result.intent.intent_type is DictationIntentType.UNKNOWN
    records = await read_intents(tmp_db_path)
    assert records[0].intent_type == "unknown"  # type: ignore[attr-defined]
    assert list(vault.iterdir()) == []


async def test_wake_word_alone_records_unknown_without_routing(
    tmp_db_path: Path, real_migrations_dir: Path, tmp_path: Path
) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    route = FakeRoute({})
    finalizer = make_finalizer(tmp_db_path, real_migrations_dir, vault, route, None)

    result = await finalizer.finalize("Omni")

    assert result.mode is DictationMode.COMMAND
    assert result.intent is not None
    assert result.intent.intent_type is DictationIntentType.UNKNOWN
    assert result.intent.parse_error == "empty command after wake word"
    assert route.calls == []  # nothing to parse -> no cloud call
    records = await read_intents(tmp_db_path)
    assert records[0].raw_text == "Omni"  # type: ignore[attr-defined]


def test_final_result_is_immutable() -> None:
    """The result feeds dictation.final — a mutable result could drift
    between what happened and what is reported."""
    result = DictationFinalResult(mode=DictationMode.NOTE, text="x")
    try:
        result.text = "y"  # type: ignore[misc]
        raise AssertionError("DictationFinalResult must be frozen")
    except AttributeError:
        pass
