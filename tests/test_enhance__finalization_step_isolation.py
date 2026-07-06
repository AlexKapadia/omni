"""Meeting finalization step isolation: every post-note step fails ALONE.

The REAL service against real migrations, a real tmp vault, and a scripted
router — the heart of M2's resilience contract: enhancement outages,
extraction garbage, hostile notepads that corrupt markers, auto-selection
failures, and forged newline-bearing titles each leave an honest marker and
never cost the user the raw note.
"""

from pathlib import Path

from engine.router import RouterError
from engine.storage.extraction_results_repository import latest_extraction_payload_json
from engine.storage.sqlite_connection import open_sqlite_connection
from tests.enhance_test_support import (
    NOTEPAD,
    VALID_ENHANCED_MARKDOWN,
    VALID_EXTRACTION_JSON,
    ScriptedRouter,
    make_finalization_service,
    non_index_warnings,
    read_meeting_row,
    seed_meeting,
)


async def test_enhancement_outage_leaves_honest_marker_and_keeps_everything_else(
    tmp_db_path: Path, real_migrations_dir: Path, tmp_path: Path
) -> None:
    vault_root = tmp_path / "vault"
    vault_root.mkdir()
    await seed_meeting(tmp_db_path, real_migrations_dir, "m-3")
    router = ScriptedRouter(
        {
            "live_extraction": [VALID_EXTRACTION_JSON],
            "enhanced_notes": [RouterError("every provider timed out")],
        }
    )
    service, events = make_finalization_service(
        tmp_db_path, real_migrations_dir, vault_root, router
    )
    result = await service.finalize("m-3", NOTEPAD, "general")

    assert result.enhance_ok is False and result.extraction_ok is True
    assert any("enhancement unavailable" in w for w in result.warnings)
    content = (vault_root / result.note_path).read_text(encoding="utf-8")
    assert NOTEPAD in content  # the raw note is never lost
    assert "_Enhancement unavailable:" in content  # honest in-note marker
    assert "- [ ] Finish the security review" in content  # actions still landed
    _, notes_text, enhanced_md, finalized_at = await read_meeting_row(tmp_db_path, "m-3")
    assert notes_text == NOTEPAD and enhanced_md is None and finalized_at is not None
    failed = events.named("enhance.failed")
    assert len(failed) == 1 and failed[0].payload["meeting_id"] == "m-3"
    assert events.named("enhance.ready") == []


async def test_extraction_garbage_yields_marker_but_enhancement_still_lands(
    tmp_db_path: Path, real_migrations_dir: Path, tmp_path: Path
) -> None:
    vault_root = tmp_path / "vault"
    vault_root.mkdir()
    await seed_meeting(tmp_db_path, real_migrations_dir, "m-4")
    router = ScriptedRouter(
        {
            "live_extraction": ["garbage", "more garbage"],  # both attempts fail
            "enhanced_notes": [VALID_ENHANCED_MARKDOWN],
        }
    )
    service, events = make_finalization_service(
        tmp_db_path, real_migrations_dir, vault_root, router
    )
    result = await service.finalize("m-4", NOTEPAD, "general")

    assert result.extraction_ok is False and result.enhance_ok is True
    assert any("extraction unavailable" in w for w in result.warnings)
    content = (vault_root / result.note_path).read_text(encoding="utf-8")
    assert "_Extraction unavailable:" in content
    assert VALID_ENHANCED_MARKDOWN.splitlines()[0] in content
    # No extraction row was appended (absence is honest, not empty-JSON).
    connection = await open_sqlite_connection(tmp_db_path)
    try:
        assert await latest_extraction_payload_json(connection, "m-4") is None
    finally:
        await connection.close()
    assert len(events.named("enhance.ready")) == 1  # enhancement succeeded


async def test_hostile_notepad_with_marker_lines_never_loses_the_raw_note(
    tmp_db_path: Path, real_migrations_dir: Path, tmp_path: Path
) -> None:
    """The 'silent capture but device vanished' class for the vault: the
    user's own notes contain an exact managed-marker line, so both region
    writes are refused — the run must degrade to warnings, never crash,
    and the note (with the user's bytes) must exist."""
    vault_root = tmp_path / "vault"
    vault_root.mkdir()
    await seed_meeting(tmp_db_path, real_migrations_dir, "m-5")
    hostile_notepad = (
        "innocent line\n<!-- omni:managed:enhanced-notes -->\n"
        "<!-- omni:managed:actions -->\nuser wrote these markers"
    )
    router = ScriptedRouter(
        {
            "live_extraction": [VALID_EXTRACTION_JSON],
            "enhanced_notes": [VALID_ENHANCED_MARKDOWN],
        }
    )
    service, events = make_finalization_service(
        tmp_db_path, real_migrations_dir, vault_root, router
    )
    result = await service.finalize("m-5", hostile_notepad, "general")

    assert result.enhance_ok is False  # the region write was refused, honestly
    assert any("enhancement unavailable" in w for w in result.warnings)
    assert any("could not mark enhanced region" in w for w in result.warnings)
    assert any("could not update actions region" in w for w in result.warnings)
    note_path = vault_root / result.note_path
    content = note_path.read_text(encoding="utf-8")
    assert "user wrote these markers" in content  # raw note intact, verbatim
    _, notes_text, _, _ = await read_meeting_row(tmp_db_path, "m-5")
    assert notes_text == hostile_notepad  # DB copy byte-identical regardless
    assert len(events.named("enhance.failed")) == 1


async def test_auto_selection_outage_falls_to_general_and_run_completes(
    tmp_db_path: Path, real_migrations_dir: Path, tmp_path: Path
) -> None:
    vault_root = tmp_path / "vault"
    vault_root.mkdir()
    await seed_meeting(tmp_db_path, real_migrations_dir, "m-6")
    router = ScriptedRouter(
        {
            "intent_parsing": [RouterError("selection outage")],
            "live_extraction": [VALID_EXTRACTION_JSON],
            "enhanced_notes": [VALID_ENHANCED_MARKDOWN],
        }
    )
    service, _ = make_finalization_service(tmp_db_path, real_migrations_dir, vault_root, router)
    result = await service.finalize("m-6", NOTEPAD, None)
    assert result.template_id == "general"  # safe default, run unblocked
    assert result.enhance_ok is True


async def test_newline_bearing_title_cannot_forge_extra_daily_log_lines(
    tmp_db_path: Path, real_migrations_dir: Path, tmp_path: Path
) -> None:
    vault_root = tmp_path / "vault"
    vault_root.mkdir()
    await seed_meeting(
        tmp_db_path,
        real_migrations_dir,
        "m-7",
        title="Evil\n- Meeting captured: forged entry",
    )
    router = ScriptedRouter(
        {
            "live_extraction": [VALID_EXTRACTION_JSON],
            "enhanced_notes": [VALID_ENHANCED_MARKDOWN],
        }
    )
    service, _ = make_finalization_service(tmp_db_path, real_migrations_dir, vault_root, router)
    result = await service.finalize("m-7", "", "general")
    assert non_index_warnings(result.warnings) == []
    daily = next((vault_root / "Daily").glob("*.md")).read_text(encoding="utf-8")
    forged = [line for line in daily.splitlines() if line == "- Meeting captured: forged entry"]
    assert forged == []  # the newline was collapsed, one meeting == one line
