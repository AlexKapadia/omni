"""When meeting.finalize omits template, use the saved active_template setting.

Proves the Settings template picker is not dead: a stored non-auto id is
applied, auto still runs auto-selection, and an explicit payload id still wins.
"""

from pathlib import Path

from engine.storage.app_settings_repository import SETTING_ACTIVE_TEMPLATE, write_setting
from engine.storage.sqlite_connection import open_sqlite_connection
from tests.enhance_test_support import (
    VALID_ENHANCED_MARKDOWN,
    VALID_EXTRACTION_JSON,
    ScriptedRouter,
    make_finalization_service,
    seed_meeting,
)


async def _set_active_template(db_path: Path, template_id: str) -> None:
    connection = await open_sqlite_connection(db_path)
    try:
        await write_setting(connection, SETTING_ACTIVE_TEMPLATE, template_id)
    finally:
        await connection.close()


async def test_none_payload_uses_saved_active_template_and_skips_auto(
    tmp_db_path: Path, real_migrations_dir: Path, tmp_path: Path
) -> None:
    vault_root = tmp_path / "vault"
    vault_root.mkdir()
    await seed_meeting(tmp_db_path, real_migrations_dir, "m-active")
    await _set_active_template(tmp_db_path, "standup")
    router = ScriptedRouter(
        {
            "live_extraction": [VALID_EXTRACTION_JSON],
            "enhanced_notes": [VALID_ENHANCED_MARKDOWN],
        }
    )
    service, _ = make_finalization_service(tmp_db_path, real_migrations_dir, vault_root, router)

    result = await service.finalize("m-active", "", None)

    assert result.template_id == "standup"
    assert router.calls_for("intent_parsing") == []


async def test_none_payload_with_auto_setting_still_runs_auto_selection(
    tmp_db_path: Path, real_migrations_dir: Path, tmp_path: Path
) -> None:
    vault_root = tmp_path / "vault"
    vault_root.mkdir()
    await seed_meeting(tmp_db_path, real_migrations_dir, "m-auto")
    await _set_active_template(tmp_db_path, "auto")
    router = ScriptedRouter(
        {
            "intent_parsing": ['{"template_id": "interview"}'],
            "live_extraction": [VALID_EXTRACTION_JSON],
            "enhanced_notes": [VALID_ENHANCED_MARKDOWN],
        }
    )
    service, _ = make_finalization_service(tmp_db_path, real_migrations_dir, vault_root, router)

    result = await service.finalize("m-auto", "", None)

    assert result.template_id == "interview"
    assert len(router.calls_for("intent_parsing")) == 1


async def test_explicit_payload_template_wins_over_active_template_setting(
    tmp_db_path: Path, real_migrations_dir: Path, tmp_path: Path
) -> None:
    vault_root = tmp_path / "vault"
    vault_root.mkdir()
    await seed_meeting(tmp_db_path, real_migrations_dir, "m-explicit")
    await _set_active_template(tmp_db_path, "standup")
    router = ScriptedRouter(
        {
            "live_extraction": [VALID_EXTRACTION_JSON],
            "enhanced_notes": [VALID_ENHANCED_MARKDOWN],
        }
    )
    service, _ = make_finalization_service(tmp_db_path, real_migrations_dir, vault_root, router)

    result = await service.finalize("m-explicit", "", "sales")

    assert result.template_id == "sales"
    assert router.calls_for("intent_parsing") == []
