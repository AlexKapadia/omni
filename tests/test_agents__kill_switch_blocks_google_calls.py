"""Kill-switch egress tests: engaged means NO Google call — but local
vault tools keep working (fail closed on egress, never on the user's own
data, claude.md §5.6 project binding).

Every gateway function must refuse BEFORE touching the session, so with
the switch engaged the fake session records zero requests.
"""

from pathlib import Path

import pytest

from engine.agents.default_tool_registry import build_default_tool_registry
from engine.agents.vault_write_note_tool import VaultWriteNoteParams
from engine.google.google_api_gateway import (
    create_calendar_event,
    create_gmail_draft,
    create_google_contact,
    query_free_busy,
)
from engine.google.google_auth_errors import GoogleEgressBlockedError
from engine.security.kill_switch import set_kill_switch_runtime_override
from tests.agents_test_support import FakeGoogleSession


@pytest.fixture()
def engaged_kill_switch():  # type: ignore[no-untyped-def]
    """Engage via the runtime override (beats env), restore afterwards."""
    set_kill_switch_runtime_override(True)
    try:
        yield
    finally:
        set_kill_switch_runtime_override(None)


async def test_calendar_event_refused_before_any_session_touch(
    engaged_kill_switch: None,
) -> None:
    session = FakeGoogleSession()
    with pytest.raises(GoogleEgressBlockedError):
        await create_calendar_event(
            session,
            title="t",
            start_iso="2026-07-10T13:00:00+00:00",
            end_iso="2026-07-10T14:00:00+00:00",
        )
    assert session.requests == []  # refused BEFORE egress, not after


async def test_free_busy_refused(engaged_kill_switch: None) -> None:
    session = FakeGoogleSession()
    with pytest.raises(GoogleEgressBlockedError):
        await query_free_busy(
            session,
            time_min_iso="2026-07-10T09:00:00+00:00",
            time_max_iso="2026-07-10T18:00:00+00:00",
        )
    assert session.requests == []


async def test_contact_sync_refused(engaged_kill_switch: None) -> None:
    session = FakeGoogleSession()
    with pytest.raises(GoogleEgressBlockedError):
        await create_google_contact(session, name="Ana Cruz")
    assert session.requests == []


async def test_gmail_draft_refused(engaged_kill_switch: None) -> None:
    session = FakeGoogleSession()
    with pytest.raises(GoogleEgressBlockedError):
        await create_gmail_draft(session, to=(), subject="s", body_text="b")
    assert session.requests == []


async def test_local_vault_tool_still_works_with_switch_engaged(
    engaged_kill_switch: None, tmp_path: Path
) -> None:
    """The user's own data never fails closed: note writing must succeed."""
    vault = tmp_path / "vault"
    vault.mkdir()
    tool = build_default_tool_registry(vault).tool_for_card_type("write_note")
    result = await tool.execute(
        VaultWriteNoteParams(title="Offline note", body_markdown="still works"),
        FakeGoogleSession(),
    )
    assert result.summary_line == "Note saved: Offline note.md"
    assert (vault / "Inbox" / "Offline note.md").exists()
    assert result.data_sent_off_machine == ""  # and honestly, nothing egressed


async def test_disengaging_the_switch_lets_calls_through_again(tmp_path: Path) -> None:
    """The refusal is the switch, not a latch: off means calls flow."""
    set_kill_switch_runtime_override(True)
    session = FakeGoogleSession([{"resourceName": "people/c1"}])
    try:
        with pytest.raises(GoogleEgressBlockedError):
            await create_google_contact(session, name="Ana Cruz")
    finally:
        set_kill_switch_runtime_override(False)
    try:
        created = await create_google_contact(session, name="Ana Cruz")
        assert created.resource_name == "people/c1"
        assert len(session.requests) == 1
    finally:
        set_kill_switch_runtime_override(None)
