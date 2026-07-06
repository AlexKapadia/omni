"""Meeting finalization: full pipeline on real DB + real vault, step isolation.

The REAL service against real migrations, a real tmp vault, and a scripted
router. Proves the happy path end-to-end (note, regions, DB row, append-only
extraction, daily line, events) and — the heart of M2's resilience contract —
that every post-note step fails ALONE: enhancement outages, hostile notepads
that corrupt markers, extraction garbage, and auto-selection failures each
leave an honest marker and never cost the user the raw note.
"""

import json
from pathlib import Path

import aiosqlite
import pytest

from engine.enhance import (
    FinalizeRefusedError,
    MeetingFinalizationService,
)
from engine.protocol import EventBroadcastHub
from engine.router import RouterError
from engine.storage.extraction_results_repository import latest_extraction_payload_json
from engine.storage.sqlite_connection import open_sqlite_connection
from engine.vault.vault_errors import VaultNotConfiguredError
from tests.enhance_test_support import (
    VALID_ENHANCED_MARKDOWN,
    VALID_EXTRACTION_JSON,
    EventCollector,
    ScriptedRouter,
    seed_meeting,
)

HAPPY_SCRIPT: dict[str, list[str | RouterError]] = {
    "intent_parsing": ['{"template_id": "sales"}'],
    "live_extraction": [VALID_EXTRACTION_JSON],
    "enhanced_notes": [VALID_ENHANCED_MARKDOWN],
}

NOTEPAD = "rough notes:\n- ask about SSO\n- reveiw pricing (typo kept!)"


def make_service(
    tmp_db_path: Path,
    real_migrations_dir: Path,
    vault_root: Path,
    router: ScriptedRouter,
) -> tuple[MeetingFinalizationService, EventCollector]:
    hub = EventBroadcastHub()
    collector = EventCollector(hub)
    service = MeetingFinalizationService(
        db_path=tmp_db_path,
        migrations_dir=real_migrations_dir,
        hub=hub,
        router_factory=lambda _recorder: router,
        vault_root_resolver=lambda: vault_root,
    )
    return service, collector


async def read_meeting_row(db_path: Path, meeting_id: str) -> tuple[object, ...]:
    connection = await aiosqlite.connect(db_path)
    try:
        cursor = await connection.execute(
            "SELECT note_path, notes_text, enhanced_notes_md, finalized_at"
            " FROM meetings WHERE id = ?",
            (meeting_id,),
        )
        row = await cursor.fetchone()
        await cursor.close()
        assert row is not None
        return tuple(row)
    finally:
        await connection.close()


def non_index_warnings(warnings: tuple[str, ...]) -> list[str]:
    """Indexing is optional-dependency-gated in unit runs; everything else
    in the warning list is a real defect for these scenarios."""
    return [w for w in warnings if "indexing unavailable" not in w]


# --------------------------------------------------------------- happy path
async def test_full_finalization_writes_note_regions_db_events_and_daily_line(
    tmp_db_path: Path, real_migrations_dir: Path, tmp_path: Path
) -> None:
    vault_root = tmp_path / "vault"
    vault_root.mkdir()
    await seed_meeting(tmp_db_path, real_migrations_dir, "m-1")
    router = ScriptedRouter({k: list(v) for k, v in HAPPY_SCRIPT.items()})
    service, events = make_service(tmp_db_path, real_migrations_dir, vault_root, router)

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
    service, _ = make_service(tmp_db_path, real_migrations_dir, vault_root, router)
    result = await service.finalize("m-2", "", "standup")
    assert result.template_id == "standup"
    assert router.calls_for("intent_parsing") == []  # never consulted


# ------------------------------------------------------------ step isolation
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
    service, events = make_service(tmp_db_path, real_migrations_dir, vault_root, router)
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
    service, events = make_service(tmp_db_path, real_migrations_dir, vault_root, router)
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
    service, events = make_service(tmp_db_path, real_migrations_dir, vault_root, router)
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
    service, _ = make_service(tmp_db_path, real_migrations_dir, vault_root, router)
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
    service, _ = make_service(tmp_db_path, real_migrations_dir, vault_root, router)
    result = await service.finalize("m-7", "", "general")
    assert non_index_warnings(result.warnings) == []
    daily = next((vault_root / "Daily").glob("*.md")).read_text(encoding="utf-8")
    forged = [line for line in daily.splitlines() if line == "- Meeting captured: forged entry"]
    assert forged == []  # the newline was collapsed, one meeting == one line


# ------------------------------------------------------- fail-closed refusals
async def test_refusals_happen_before_any_write_or_event(
    tmp_db_path: Path, real_migrations_dir: Path, tmp_path: Path
) -> None:
    vault_root = tmp_path / "vault"
    vault_root.mkdir()
    await seed_meeting(tmp_db_path, real_migrations_dir, "open-meeting", ended_at=None)
    await seed_meeting(tmp_db_path, real_migrations_dir, "ended-meeting")
    router = ScriptedRouter({})
    service, events = make_service(tmp_db_path, real_migrations_dir, vault_root, router)

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
    service, _ = make_service(tmp_db_path, real_migrations_dir, vault_root, router)
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


# ------------------------------------------------------------- library reads
async def test_list_and_get_serve_the_finalized_meeting(
    tmp_db_path: Path, real_migrations_dir: Path, tmp_path: Path
) -> None:
    vault_root = tmp_path / "vault"
    vault_root.mkdir()
    await seed_meeting(tmp_db_path, real_migrations_dir, "m-10")
    router = ScriptedRouter(
        {
            "live_extraction": [VALID_EXTRACTION_JSON],
            "enhanced_notes": [VALID_ENHANCED_MARKDOWN],
        }
    )
    service, _ = make_service(tmp_db_path, real_migrations_dir, vault_root, router)
    await service.finalize("m-10", NOTEPAD, "general")

    rows = await service.list_meetings()
    assert [row.id for row in rows] == ["m-10"]
    found = await service.get_meeting("m-10")
    assert found is not None
    row, segments = found
    assert row.notes_text == NOTEPAD
    assert [s.stream for s in segments] == ["them", "me", "them", "me"]
    assert await service.get_meeting("ghost") is None
