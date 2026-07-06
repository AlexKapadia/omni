"""Meeting finalization fail-closed refusals: refuse BEFORE any side effect.

The REAL service against real migrations and a real tmp vault. Proves every
refusal (ghost meeting, still-capturing, unknown template, duplicate
finalize, unconfigured vault) happens before any write, event, or model
call — nothing escapes a refused run.
"""

from pathlib import Path

import pytest

from engine.enhance import (
    FinalizeRefusedError,
    MeetingFinalizationService,
)
from engine.protocol import EventBroadcastHub
from engine.vault.vault_errors import VaultNotConfiguredError
from tests.enhance_test_support import (
    NOTEPAD,
    VALID_ENHANCED_MARKDOWN,
    VALID_EXTRACTION_JSON,
    EventCollector,
    ScriptedRouter,
    make_finalization_service,
    read_meeting_row,
    seed_meeting,
)


async def test_refusals_happen_before_any_write_or_event(
    tmp_db_path: Path, real_migrations_dir: Path, tmp_path: Path
) -> None:
    vault_root = tmp_path / "vault"
    vault_root.mkdir()
    await seed_meeting(tmp_db_path, real_migrations_dir, "open-meeting", ended_at=None)
    await seed_meeting(tmp_db_path, real_migrations_dir, "ended-meeting")
    router = ScriptedRouter({})
    service, events = make_finalization_service(
        tmp_db_path, real_migrations_dir, vault_root, router
    )

    with pytest.raises(FinalizeRefusedError, match="does not exist"):
        await service.finalize("ghost", "", None)
    with pytest.raises(FinalizeRefusedError, match="still capturing"):
        await service.finalize("open-meeting", "", None)
    with pytest.raises(FinalizeRefusedError, match="unknown template"):
        await service.finalize("ended-meeting", "", "not_a_template")

    assert events.events == []  # no event escaped a refused run
    assert list(vault_root.iterdir()) == []  # no file was written
    assert router.calls == []  # no model call was made


async def test_duplicate_finalize_is_refused_and_the_note_is_not_forked(
    tmp_db_path: Path, real_migrations_dir: Path, tmp_path: Path
) -> None:
    vault_root = tmp_path / "vault"
    vault_root.mkdir()
    await seed_meeting(tmp_db_path, real_migrations_dir, "m-8")
    router = ScriptedRouter(
        {
            "live_extraction": [VALID_EXTRACTION_JSON, VALID_EXTRACTION_JSON],
            "enhanced_notes": [VALID_ENHANCED_MARKDOWN, VALID_ENHANCED_MARKDOWN],
        }
    )
    service, _ = make_finalization_service(tmp_db_path, real_migrations_dir, vault_root, router)
    await service.finalize("m-8", NOTEPAD, "general")
    with pytest.raises(FinalizeRefusedError, match="already finalized"):
        await service.finalize("m-8", NOTEPAD, "general")
    assert len(list((vault_root / "Meetings").glob("*.md"))) == 1  # no fork


async def test_unconfigured_vault_refuses_without_touching_anything(
    tmp_db_path: Path, real_migrations_dir: Path, tmp_path: Path
) -> None:
    await seed_meeting(tmp_db_path, real_migrations_dir, "m-9")
    hub = EventBroadcastHub()
    events = EventCollector(hub)

    def no_vault() -> Path:
        raise VaultNotConfiguredError("OMNI_VAULT_DIR is not set")

    service = MeetingFinalizationService(
        db_path=tmp_db_path,
        migrations_dir=real_migrations_dir,
        hub=hub,
        router_factory=lambda _recorder: ScriptedRouter({}),
        vault_root_resolver=no_vault,
    )
    with pytest.raises(FinalizeRefusedError, match="OMNI_VAULT_DIR"):
        await service.finalize("m-9", NOTEPAD, None)
    assert events.events == []
    _, notes_text, _, finalized_at = await read_meeting_row(tmp_db_path, "m-9")
    assert notes_text is None and finalized_at is None  # nothing was stamped
