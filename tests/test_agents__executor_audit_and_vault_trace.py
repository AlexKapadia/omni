"""Executor audit completeness + vault trace: every attempt leaves ONE row.

Invariants under test (claude.md §5.6 immutable audit): every execution
attempt — success AND failure — appends exactly one audit_log row naming
what ran, the mapping path, the provider (None when deterministic), and
what data left the machine; the meeting note's Actions region and the
daily note each gain exactly one line on success; a failed tool leaves the
card 'failed' with the plain-voice reason and NO vault lines.
"""

import json
from pathlib import Path

import pytest

from engine.agents.agents_errors import ToolExecutionError
from engine.agents.approval_card_types import CardType
from engine.agents.card_executor import execute_approved_card
from engine.agents.default_tool_registry import build_default_tool_registry
from engine.agents.tool_registry import AgentTool, ToolRegistry, ToolResult
from engine.agents.vault_write_note_tool import VaultWriteNoteParams
from engine.vault.managed_region_rewriter import render_managed_region
from engine.vault.meeting_note_writer import create_meeting_note
from tests.agents_test_support import (
    FakeGoogleSession,
    approved_card,
    audit_rows,
    card_status,
    insert_meeting,
    migrated_connection,
)


class ExplodingTool(AgentTool):
    name = "exploding_tool"
    card_type = CardType.WRITE_NOTE
    params_model = VaultWriteNoteParams
    description = "always fails"

    def dry_run(self, params: object) -> tuple[str, ...]:
        return ("boom",)

    async def execute(self, params: object, google_session: object) -> ToolResult:
        raise ToolExecutionError(self.name, "the disk is full of regrets")


async def test_success_writes_exactly_one_audit_row_with_full_account(
    tmp_db_path: Path, real_migrations_dir: Path, tmp_path: Path
) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    conn = await migrated_connection(tmp_db_path, real_migrations_dir)
    try:
        note_path = create_meeting_note(vault, title="Sync", date_iso="2026-07-06")
        await insert_meeting(conn, note_path=str(note_path))
        card_id = await approved_card(
            conn,
            card_type="write_note",
            payload_json='{"title": "Follow-ups", "body_markdown": "- ping Tom"}',
            meeting_id="m-1",
        )
        report = await execute_approved_card(
            conn,
            card_id,
            registry=build_default_tool_registry(vault),
            google_session=FakeGoogleSession(),
            vault_root=vault,
        )
        assert report.final_status == "executed"
        assert report.mapping == "deterministic"
        assert report.provider is None  # no model involved -> honestly None
        assert report.vault_trace_error is None

        rows = await audit_rows(conn)
        assert len(rows) == 1  # exactly one audit row per attempt
        action, payload_json, result_json = rows[0]
        assert action == "agent.card_executed"
        payload = json.loads(payload_json)
        assert payload["card_id"] == card_id
        assert payload["card_type"] == "write_note"
        assert payload["mapping"] == "deterministic"
        assert payload["provider"] is None
        assert payload["data_sent_off_machine"] == ""  # local-only: nothing left
        assert "summary" in json.loads(result_json)
        assert await card_status(conn, card_id) == "executed"
    finally:
        await conn.close()


async def test_success_appends_one_actions_line_and_one_daily_line(
    tmp_db_path: Path, real_migrations_dir: Path, tmp_path: Path
) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    conn = await migrated_connection(tmp_db_path, real_migrations_dir)
    try:
        note_path = create_meeting_note(vault, title="Sync", date_iso="2026-07-06")
        note_before = note_path.read_text(encoding="utf-8")
        await insert_meeting(conn, note_path=str(note_path))
        card_id = await approved_card(
            conn,
            card_type="write_note",
            payload_json='{"title": "T", "body_markdown": "B"}',
            meeting_id="m-1",
        )
        await execute_approved_card(
            conn,
            card_id,
            registry=build_default_tool_registry(vault),
            google_session=FakeGoogleSession(),
            vault_root=vault,
        )
        note_after = note_path.read_text(encoding="utf-8")
        assert note_after != note_before
        assert note_after.count("Omni (write_note): Note saved: T.md") == 1
        # the placeholder scaffolding was replaced, not kept above the line
        assert "_No actions yet._" not in note_after
        # user territory untouched: everything before the Actions region is
        # byte-identical (the managed rewriter guarantees it; we spot-check)
        assert note_after.split("## Actions")[0] == note_before.split("## Actions")[0]

        daily_files = list((vault / "Daily").glob("*.md"))
        assert len(daily_files) == 1
        daily = daily_files[0].read_text(encoding="utf-8")
        assert daily.count("Omni (write_note)") == 1
    finally:
        await conn.close()


async def test_failure_writes_exactly_one_audit_row_and_no_vault_lines(
    tmp_db_path: Path, real_migrations_dir: Path, tmp_path: Path
) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    conn = await migrated_connection(tmp_db_path, real_migrations_dir)
    try:
        card_id = await approved_card(conn)
        report = await execute_approved_card(
            conn,
            card_id,
            registry=ToolRegistry((ExplodingTool(),)),
            google_session=FakeGoogleSession(),
            vault_root=vault,
        )
        assert report.final_status == "failed"
        assert report.error is not None and "regrets" in report.error
        rows = await audit_rows(conn)
        assert len(rows) == 1  # failure is audited too — exactly once
        action, _, result_json = rows[0]
        assert action == "agent.card_execution_failed"
        assert "regrets" in json.loads(result_json)["error"]
        assert await card_status(conn, card_id) == "failed"
        assert not (vault / "Daily").exists()  # nothing ran -> no trace lines
    finally:
        await conn.close()


async def test_invalid_stored_payload_fails_typed_with_one_audit_row(
    tmp_db_path: Path, real_migrations_dir: Path, tmp_path: Path
) -> None:
    """A payload that no longer validates must fail closed, not best-effort."""
    conn = await migrated_connection(tmp_db_path, real_migrations_dir)
    try:
        card_id = await approved_card(
            conn, card_type="write_note", payload_json='{"unexpected": "keys"}'
        )
        report = await execute_approved_card(
            conn,
            card_id,
            registry=build_default_tool_registry(tmp_path),
            google_session=FakeGoogleSession(),
            vault_root=None,
        )
        assert report.final_status == "failed"
        assert len(await audit_rows(conn)) == 1
        assert await card_status(conn, card_id) == "failed"
    finally:
        await conn.close()


async def test_ambiguous_card_without_router_fails_honestly(
    tmp_db_path: Path, real_migrations_dir: Path, tmp_path: Path
) -> None:
    """create_event with only a natural-language hint and no router: the
    executor must refuse with the reason, never invent a datetime."""
    conn = await migrated_connection(tmp_db_path, real_migrations_dir)
    try:
        card_id = await approved_card(
            conn,
            card_type="create_event",
            payload_json='{"title": "Lunch with Tom", "when_hint": "Friday at 1"}',
        )
        report = await execute_approved_card(
            conn,
            card_id,
            registry=build_default_tool_registry(tmp_path),
            google_session=FakeGoogleSession(),
            vault_root=None,
            router=None,
        )
        assert report.final_status == "failed"
        assert report.error is not None and "no router" in report.error
        assert report.mapping == "llm"  # it got as far as needing the LLM
        assert len(await audit_rows(conn)) == 1
    finally:
        await conn.close()


async def test_vault_trace_failure_is_reported_but_card_still_executes(
    tmp_db_path: Path, real_migrations_dir: Path, tmp_path: Path
) -> None:
    """Corrupt the Actions region AFTER approval: the note append must fail
    closed, but the executed action stays executed and the report says why."""
    vault = tmp_path / "vault"
    vault.mkdir()
    conn = await migrated_connection(tmp_db_path, real_migrations_dir)
    try:
        note_path = create_meeting_note(vault, title="Sync", date_iso="2026-07-06")
        # Sabotage: duplicate the actions region -> ambiguous markers.
        content = note_path.read_text(encoding="utf-8")
        note_path.write_text(
            content + "\n" + render_managed_region("actions", "dup"), encoding="utf-8"
        )
        await insert_meeting(conn, note_path=str(note_path))
        card_id = await approved_card(
            conn,
            card_type="write_note",
            payload_json='{"title": "T", "body_markdown": "B"}',
            meeting_id="m-1",
        )
        report = await execute_approved_card(
            conn,
            card_id,
            registry=build_default_tool_registry(vault),
            google_session=FakeGoogleSession(),
            vault_root=vault,
        )
        assert report.final_status == "executed"  # the action itself succeeded
        assert report.vault_trace_error is not None  # ...and the gap is honest
        rows = await audit_rows(conn)
        assert len(rows) == 1
    finally:
        await conn.close()


@pytest.mark.parametrize("attempts", [3])
async def test_n_attempts_produce_exactly_n_audit_rows(
    tmp_db_path: Path, real_migrations_dir: Path, tmp_path: Path, attempts: int
) -> None:
    """Audit rows scale 1:1 with attempts — never 0, never 2 per attempt."""
    conn = await migrated_connection(tmp_db_path, real_migrations_dir)
    try:
        registry = build_default_tool_registry(tmp_path)
        for i in range(attempts):
            card_id = await approved_card(
                conn,
                card_type="write_note",
                payload_json=json.dumps({"title": f"T{i}", "body_markdown": "B"}),
                source_row_id=i + 1,
            )
            await execute_approved_card(
                conn, card_id, registry=registry,
                google_session=FakeGoogleSession(), vault_root=None,
            )
        assert len(await audit_rows(conn)) == attempts
    finally:
        await conn.close()
