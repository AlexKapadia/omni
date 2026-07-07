"""M7 instant-execute whitelist: deny-by-default direct execution.

The whitelist is the ONLY way a dictation intent skips the approval click,
and it must never skip the AUDIT. Adversarial coverage: with no whitelist
(and with an empty one) a dictation card stays PENDING (approval-before-
execute); only an intent type in the persisted whitelist triggers the
auto-execute callback — and it is handed the exact created card id, so the
same audited approve->execute path runs (never a side channel).
"""

from pathlib import Path

from engine.dictation.dictation_finalization import DictationFinalResult
from engine.dictation.dictation_intent_schema import DictationIntentType, ParsedIntent
from engine.dictation.dictation_intents_repository import insert_dictation_intent
from engine.dictation.dictation_mode_splitter import DictationMode
from engine.protocol import EventBroadcastHub
from engine.storage.app_settings_repository import (
    SETTING_INSTANT_EXECUTE_WHITELIST,
    write_setting,
)
from engine.storage.sqlite_connection import open_sqlite_connection
from engine.storage.sqlite_migrations_runner import apply_migrations
from engine.wiring.approval_card_build_server_wiring import ApprovalCardBuildWiring

_MIGRATIONS = Path(__file__).resolve().parent.parent / "migrations"


async def _seed_write_note_intent(db: Path) -> int:
    await apply_migrations(db, _MIGRATIONS)
    connection = await open_sqlite_connection(db)
    try:
        return await insert_dictation_intent(
            connection,
            ts="2026-07-06T10:00:00+00:00",
            raw_text="Omni, note that the vendor call moved to Friday",
            intent=ParsedIntent(
                intent_type=DictationIntentType.WRITE_NOTE,
                fields={"title": "Vendor call moved", "body": "moved to Friday"},
                confidence=0.95,
            ),
            provider="groq",
            model="test-model",
        )
    finally:
        await connection.close()


async def _set_whitelist(db: Path, values: list[str]) -> None:
    connection = await open_sqlite_connection(db)
    try:
        await write_setting(connection, SETTING_INSTANT_EXECUTE_WHITELIST, values)
    finally:
        await connection.close()


async def _card_statuses(db: Path) -> list[str]:
    connection = await open_sqlite_connection(db)
    try:
        cursor = await connection.execute("SELECT status FROM approval_cards ORDER BY id")
        rows = await cursor.fetchall()
        await cursor.close()
    finally:
        await connection.close()
    return [str(row[0]) for row in rows]


def _result(intent_row_id: int) -> DictationFinalResult:
    return DictationFinalResult(
        mode=DictationMode.COMMAND,
        text="Omni, note that the vendor call moved to Friday",
        intent_row_id=intent_row_id,
    )


async def test_whitelisted_intent_triggers_auto_execute_with_the_card_id(
    tmp_db_path: Path,
) -> None:
    row_id = await _seed_write_note_intent(tmp_db_path)
    await _set_whitelist(tmp_db_path, ["write_note"])  # explicit opt-in
    hub = EventBroadcastHub()
    wiring = ApprovalCardBuildWiring(hub, db_path=tmp_db_path, migrations_dir=_MIGRATIONS)
    executed: list[int] = []

    async def fake_auto_execute(card_id: int) -> None:
        executed.append(card_id)

    wiring.auto_execute_whitelisted = fake_auto_execute
    await wiring.on_dictation_final(_result(row_id))
    # The card was created AND handed to the audited approve->execute path.
    statuses = await _card_statuses(tmp_db_path)
    assert len(statuses) == 1
    assert len(executed) == 1 and executed[0] >= 1
    await wiring.shutdown()


async def test_empty_whitelist_leaves_card_pending(tmp_db_path: Path) -> None:
    row_id = await _seed_write_note_intent(tmp_db_path)
    await _set_whitelist(tmp_db_path, [])  # deny by default
    hub = EventBroadcastHub()
    wiring = ApprovalCardBuildWiring(hub, db_path=tmp_db_path, migrations_dir=_MIGRATIONS)
    executed: list[int] = []

    async def fake_auto_execute(card_id: int) -> None:
        executed.append(card_id)

    wiring.auto_execute_whitelisted = fake_auto_execute
    await wiring.on_dictation_final(_result(row_id))
    assert await _card_statuses(tmp_db_path) == ["pending"]  # approval required
    assert executed == []
    await wiring.shutdown()


async def test_no_whitelist_setting_leaves_card_pending(tmp_db_path: Path) -> None:
    row_id = await _seed_write_note_intent(tmp_db_path)
    hub = EventBroadcastHub()
    wiring = ApprovalCardBuildWiring(hub, db_path=tmp_db_path, migrations_dir=_MIGRATIONS)
    called = False

    async def fake_auto_execute(card_id: int) -> None:
        nonlocal called
        called = True

    wiring.auto_execute_whitelisted = fake_auto_execute
    await wiring.on_dictation_final(_result(row_id))
    # No setting at all => fail closed => pending, approval required.
    assert await _card_statuses(tmp_db_path) == ["pending"]
    assert called is False
    await wiring.shutdown()


async def test_non_whitelisted_type_stays_pending_when_other_type_whitelisted(
    tmp_db_path: Path,
) -> None:
    row_id = await _seed_write_note_intent(tmp_db_path)
    # Whitelist a DIFFERENT intent type; the write_note card must stay pending.
    await _set_whitelist(tmp_db_path, ["create_event"])
    hub = EventBroadcastHub()
    wiring = ApprovalCardBuildWiring(hub, db_path=tmp_db_path, migrations_dir=_MIGRATIONS)
    executed: list[int] = []

    async def fake_auto_execute(card_id: int) -> None:
        executed.append(card_id)

    wiring.auto_execute_whitelisted = fake_auto_execute
    await wiring.on_dictation_final(_result(row_id))
    assert await _card_statuses(tmp_db_path) == ["pending"]
    assert executed == []
    await wiring.shutdown()
