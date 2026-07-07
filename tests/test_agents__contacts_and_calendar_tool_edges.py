"""Contacts-upsert + calendar-create-event tool edges (validation + execute).

These two tools are the write surfaces guarded by the approval flow. The
tests pin their exact behaviour:

- Contacts: local-first vault write ALWAYS happens; Google sync is opt-in and
  its failure is reported as honest partial success, never hidden or faked.
- Create-event: only concrete, ordered ISO datetimes and real email addresses
  survive validation (fail closed); the dry-run preview shows exactly what
  will be created, truncating long notes.
"""

import json
from collections.abc import Iterator
from pathlib import Path

import pytest
from pydantic import ValidationError

from engine.agents.agents_errors import ToolExecutionError
from engine.agents.calendar_create_event_tool import (
    CalendarCreateEventParams,
    CalendarCreateEventTool,
)
from engine.agents.calendar_create_event_tool import _narrow as _narrow_event
from engine.agents.contacts_upsert_tool import ContactsUpsertParams, ContactsUpsertTool
from engine.agents.contacts_upsert_tool import _narrow as _narrow_contact
from engine.security.kill_switch import set_kill_switch_runtime_override
from tests.agents_test_support import FakeGoogleSession

_ISO_START = "2026-07-06T09:00:00+00:00"
_ISO_END = "2026-07-06T10:00:00+00:00"


@pytest.fixture(autouse=True)
def _egress_disengaged() -> Iterator[None]:
    set_kill_switch_runtime_override(False)
    yield
    set_kill_switch_runtime_override(None)


# --------------------------------------------------------------------------
# ContactsUpsertTool
# --------------------------------------------------------------------------


def test_contact_narrow_refuses_foreign_params() -> None:
    with pytest.raises(ToolExecutionError, match="expected ContactsUpsertParams"):
        _narrow_contact(
            CalendarCreateEventParams(title="X", start_iso=_ISO_START, end_iso=_ISO_END)
        )


def test_contact_dry_run_lists_present_fields_and_vault_only() -> None:
    tool = ContactsUpsertTool(Path("unused"))
    lines = tool.dry_run(
        ContactsUpsertParams(name="Ana Cruz", phone="123", company="Northwind")
    )
    assert lines == (
        "Contact: Ana Cruz",
        "Phone: 123",
        "Company: Northwind",
        "Vault only (no Google)",
    )


def test_contact_dry_run_announces_google_sync_when_opted_in() -> None:
    tool = ContactsUpsertTool(Path("unused"))
    lines = tool.dry_run(ContactsUpsertParams(name="Ana", sync_to_google=True))
    assert lines[-1] == "Also sync to Google Contacts"


async def test_contact_execute_vault_only_sends_nothing_off_machine(tmp_path: Path) -> None:
    tool = ContactsUpsertTool(tmp_path)
    session = FakeGoogleSession([])  # never touched: no sync requested
    result = await tool.execute(
        ContactsUpsertParams(name="Ana Cruz", email="ana@nw.io"), session
    )
    assert result.summary_line == "Contact saved to vault: Ana Cruz"
    assert result.detail["synced_to_google"] is False
    assert result.data_sent_off_machine == ""  # local-only invariant
    assert session.requests == []  # the gateway was never called
    note_path = Path(str(result.detail["note_path"]))
    assert note_path.exists()  # the vault write really happened


async def test_contact_execute_syncs_to_google_and_reports_resource(tmp_path: Path) -> None:
    tool = ContactsUpsertTool(tmp_path)
    session = FakeGoogleSession([{"resourceName": "people/c123"}])
    result = await tool.execute(
        ContactsUpsertParams(
            name="Ana Cruz", email="ana@nw.io", sync_to_google=True
        ),
        session,
    )
    assert result.detail["synced_to_google"] is True
    assert result.detail["google_resource_name"] == "people/c123"
    assert result.summary_line == "Contact saved to vault and Google: Ana Cruz"
    assert "Google People API" in result.data_sent_off_machine
    assert len(session.requests) == 1  # exactly one egress call


async def test_contact_execute_reports_partial_success_when_sync_fails(tmp_path: Path) -> None:
    """The People response with no resourceName raises GoogleApiCallError; the
    vault write must still stand and the sync failure be reported honestly."""
    tool = ContactsUpsertTool(tmp_path)
    session = FakeGoogleSession([{}])  # missing resourceName -> GoogleApiCallError
    result = await tool.execute(
        ContactsUpsertParams(
            name="Ana Cruz", email="ana@nw.io", sync_to_google=True
        ),
        session,
    )
    assert result.detail["synced_to_google"] is False
    assert "google_sync_error" in result.detail
    assert result.summary_line == "Contact saved to vault: Ana Cruz (Google sync failed)"
    assert result.data_sent_off_machine == ""  # nothing usable left; no claim of egress
    note_path = Path(str(result.detail["note_path"]))
    assert note_path.exists()  # local-first: the vault write survived the failure


# --------------------------------------------------------------------------
# CalendarCreateEventParams validation + tool
# --------------------------------------------------------------------------


@pytest.mark.parametrize("bad_email", ["noat", "@host.io", "user@"])
def test_create_event_rejects_non_email_attendees(bad_email: str) -> None:
    """Boundary shapes: no '@', leading '@', trailing '@' all refuse."""
    with pytest.raises(ValidationError, match="not an email address"):
        CalendarCreateEventParams(
            title="Sync",
            start_iso=_ISO_START,
            end_iso=_ISO_END,
            attendee_emails=[bad_email],
        )


def test_create_event_accepts_well_formed_attendees() -> None:
    params = CalendarCreateEventParams(
        title="Sync",
        start_iso=_ISO_START,
        end_iso=_ISO_END,
        attendee_emails=["sam@nw.io", "lee@nw.io"],
    )
    assert params.attendee_emails == ["sam@nw.io", "lee@nw.io"]


def test_create_event_rejects_non_iso_start() -> None:
    with pytest.raises(ValidationError):
        CalendarCreateEventParams(title="X", start_iso="whenever", end_iso=_ISO_END)


def test_create_event_rejects_end_not_after_start() -> None:
    with pytest.raises(ValidationError, match="end must be after its start"):
        CalendarCreateEventParams(title="X", start_iso=_ISO_END, end_iso=_ISO_END)


def test_event_narrow_refuses_foreign_params() -> None:
    with pytest.raises(ToolExecutionError, match="expected CalendarCreateEventParams"):
        _narrow_event(ContactsUpsertParams(name="Nobody"))


def test_event_dry_run_shows_invitees_and_truncates_notes() -> None:
    long_note = "N" * 200
    tool = CalendarCreateEventTool()
    lines = tool.dry_run(
        CalendarCreateEventParams(
            title="Review",
            start_iso=_ISO_START,
            end_iso=_ISO_END,
            attendee_emails=["sam@nw.io", "lee@nw.io"],
            description=long_note,
        )
    )
    assert lines[0] == "Event: Review"
    assert lines[1] == f"From {_ISO_START} to {_ISO_END}"
    assert lines[2] == "Invite: sam@nw.io, lee@nw.io"
    # The notes line is truncated to 120 chars (preview, not the whole body).
    assert lines[3] == "Notes: " + "N" * 120


def test_event_dry_run_omits_invite_and_notes_when_absent() -> None:
    tool = CalendarCreateEventTool()
    lines = tool.dry_run(
        CalendarCreateEventParams(title="Solo", start_iso=_ISO_START, end_iso=_ISO_END)
    )
    assert lines == ("Event: Solo", f"From {_ISO_START} to {_ISO_END}")


async def test_event_execute_creates_event_and_names_data_sent(tmp_path: Path) -> None:
    session = FakeGoogleSession(
        [{"id": "evt-1", "htmlLink": "https://cal/evt-1"}]
    )
    tool = CalendarCreateEventTool()
    result = await tool.execute(
        CalendarCreateEventParams(
            title="Review",
            start_iso=_ISO_START,
            end_iso=_ISO_END,
            attendee_emails=["sam@nw.io"],
        ),
        session,
    )
    assert result.detail == {"event_id": "evt-1", "html_link": "https://cal/evt-1"}
    assert result.summary_line == f"Event created: Review ({_ISO_START})"
    assert "Google Calendar API" in result.data_sent_off_machine
    # The event body carried exactly the approved attendee, nothing invented.
    _method, _url, body = session.requests[0]
    assert body is not None
    assert body["attendees"] == [{"email": "sam@nw.io"}]
    assert json.dumps(body)  # body is JSON-serialisable (no surprise objects)
