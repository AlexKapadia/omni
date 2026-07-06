"""Meeting finalization happy path: full pipeline on real DB + real vault.

The REAL service against real migrations, a real tmp vault, and a scripted
router. Proves the happy path end-to-end — note, managed regions, DB row,
append-only extraction, daily line, events — plus that an explicit template
choice skips auto-selection entirely.
"""

import json
from pathlib import Path

from engine.storage.extraction_results_repository import latest_extraction_payload_json
from engine.storage.sqlite_connection import open_sqlite_connection
from tests.enhance_test_support import (
    HAPPY_SCRIPT,
    NOTEPAD,
    VALID_ENHANCED_MARKDOWN,
    VALID_EXTRACTION_JSON,
    ScriptedRouter,
    make_finalization_service,
    non_index_warnings,
    read_meeting_row,
    seed_meeting,
)


async def test_full_finalization_writes_note_regions_db_events_and_daily_line(
    tmp_db_path: Path, real_migrations_dir: Path, tmp_path: Path
) -> None:
    vault_root = tmp_path / "vault"
    vault_root.mkdir()
    await seed_meeting(tmp_db_path, real_migrations_dir, "m-1")
    router = ScriptedRouter({k: list(v) for k, v in HAPPY_SCRIPT.items()})
    service, events = make_finalization_service(
        tmp_db_path, real_migrations_dir, vault_root, router
    )

    result = await service.finalize("m-1", NOTEPAD, None)

    # --- result payload (pinned by the TS mirror)
    assert result.meeting_id == "m-1"
    assert result.template_id == "sales"  # auto-selection chose it
    assert result.enhance_ok is True and result.extraction_ok is True
    assert non_index_warnings(result.warnings) == []

    # --- the vault note
    note_path = vault_root / result.note_path
    assert note_path.is_file()
    content = note_path.read_text(encoding="utf-8")
    assert NOTEPAD in content  # My Notes verbatim (fidelity mandate)
    assert "reveiw pricing (typo kept!)" in content  # the typo survives
    assert VALID_ENHANCED_MARKDOWN.splitlines()[0] in content
    assert "*Enhanced from your notes + transcript.*" in content
    assert "- [ ] Finish the security review — Me (due: Friday)" in content
    assert "pending your approval" in content
    assert "> [!note]- Transcript" in content  # collapsed callout
    assert "> Them: We need the security review done by Friday." in content
    assert "attendees:" in content and "Dana Vendor" in content  # seeded frontmatter

    # --- the DB row: notes byte-identical, enhancement stored, stamped
    note_rel, notes_text, enhanced_md, finalized_at = await read_meeting_row(
        tmp_db_path, "m-1"
    )
    assert note_rel == result.note_path
    assert notes_text == NOTEPAD  # exact bytes
    assert isinstance(enhanced_md, str) and enhanced_md.endswith(
        "*Enhanced from your notes + transcript.*"
    )
    assert finalized_at is not None

    # --- append-only extraction row persisted for M4's approval cards
    connection = await open_sqlite_connection(tmp_db_path)
    try:
        payload_json = await latest_extraction_payload_json(connection, "m-1")
    finally:
        await connection.close()
    assert payload_json is not None
    assert json.loads(payload_json) == json.loads(VALID_EXTRACTION_JSON)

    # --- daily-note line with the exact action count
    daily_files = list((vault_root / "Daily").glob("*.md"))
    assert len(daily_files) == 1
    daily = daily_files[0].read_text(encoding="utf-8")
    assert f"- Meeting captured: Vendor sync -> {result.note_path}" in daily
    assert "(1 action(s) pending approval)" in daily

    # --- the event story: started, then ready with the note path
    assert len(events.named("enhance.started")) == 1
    ready = events.named("enhance.ready")
    assert len(ready) == 1
    assert ready[0].payload == {"meeting_id": "m-1", "note_path": result.note_path}
    assert events.named("enhance.failed") == []


async def test_explicit_template_skips_auto_selection_entirely(
    tmp_db_path: Path, real_migrations_dir: Path, tmp_path: Path
) -> None:
    vault_root = tmp_path / "vault"
    vault_root.mkdir()
    await seed_meeting(tmp_db_path, real_migrations_dir, "m-2")
    router = ScriptedRouter(
        {
            "live_extraction": [VALID_EXTRACTION_JSON],
            "enhanced_notes": [VALID_ENHANCED_MARKDOWN],
        }
    )
    service, _ = make_finalization_service(tmp_db_path, real_migrations_dir, vault_root, router)
    result = await service.finalize("m-2", "", "standup")
    assert result.template_id == "standup"
    assert router.calls_for("intent_parsing") == []  # never consulted
