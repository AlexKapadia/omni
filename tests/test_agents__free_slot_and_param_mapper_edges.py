"""Free-slot search arithmetic + deterministic card->params mapping edges.

Two pure, high-value surfaces:

- ``first_free_slot``: the deterministic gap-finder. Every assertion pins the
  EXACT chosen (start, end) to the minute — a slot proposed one minute wrong
  would double-book the user, so the boundaries (gap == duration, clamped
  busy, intervals outside the window, overlapping/merged busy) are checked
  on/just-over/just-under.
- ``map_card_payload_to_tool_params``: the model-free translation. Each card
  type's branch is exercised, and the ambiguity refusals (missing ISO,
  bare-name recipients, fields that fail validation) are asserted to refuse
  with an honest reason rather than guess.
"""

from collections.abc import Iterator
from datetime import timedelta

import pytest
from pydantic import ValidationError

from engine.agents.agents_errors import ToolExecutionError
from engine.agents.approval_card_types import (
    CreateEventCardPayload,
    DraftEmailCardPayload,
    FindSlotCardPayload,
    UpsertContactCardPayload,
    WriteNoteCardPayload,
)
from engine.agents.calendar_create_event_tool import CalendarCreateEventParams
from engine.agents.calendar_find_free_slot_tool import (
    CalendarFindFreeSlotParams,
    CalendarFindFreeSlotTool,
    _narrow,
    _parse_iso,
    first_free_slot,
)
from engine.agents.card_to_tool_params_mapper import map_card_payload_to_tool_params
from engine.agents.contacts_upsert_tool import ContactsUpsertParams
from engine.agents.gmail_create_draft_tool import GmailCreateDraftParams
from engine.agents.vault_write_note_tool import VaultWriteNoteParams
from engine.google.google_api_gateway import BusyInterval
from engine.security.kill_switch import set_kill_switch_runtime_override
from tests.agents_test_support import FakeGoogleSession

_DAY = "2026-07-06"


@pytest.fixture(autouse=True)
def _egress_disengaged() -> Iterator[None]:
    """Pin the kill switch OFF so gateway calls run deterministically,
    regardless of any OMNI_KILL_SWITCH value in the ambient environment."""
    set_kill_switch_runtime_override(False)
    yield
    set_kill_switch_runtime_override(None)


def _iso(hhmm: str) -> str:
    return f"{_DAY}T{hhmm}:00+00:00"


def _busy(*pairs: tuple[str, str]) -> tuple[BusyInterval, ...]:
    return tuple(BusyInterval(start_iso=_iso(a), end_iso=_iso(b)) for a, b in pairs)


def _empty_window_slot(start: str, end: str, dur_minutes: int) -> tuple[str, str] | None:
    """The chosen slot for an empty (no busy) window, as ISO strings."""
    result = first_free_slot(
        (),
        window_start=_parse_iso(_iso(start)),
        window_end=_parse_iso(_iso(end)),
        duration=timedelta(minutes=dur_minutes),
    )
    if result is None:
        return None
    got_start, got_end = result
    return got_start.isoformat(), got_end.isoformat()


# --------------------------------------------------------------------------
# first_free_slot: the deterministic gap-finder, boundary-exact
# --------------------------------------------------------------------------


def test_empty_window_fits_exactly_at_window_start() -> None:
    """Gap of EXACTLY the duration at the window start qualifies (inclusive)."""
    assert _empty_window_slot("09:00", "09:30", 30) == (_iso("09:00"), _iso("09:30"))


def test_empty_window_one_minute_too_short_returns_none() -> None:
    """Just-under the duration: an honest 'no slot', never a squeezed fit."""
    assert _empty_window_slot("09:00", "09:29", 30) is None


def test_gap_before_busy_equal_to_duration_is_taken() -> None:
    """A pre-busy gap of exactly the duration wins the earliest slot."""
    result = first_free_slot(
        _busy(("09:30", "10:00")),
        window_start=_parse_iso(_iso("09:00")),
        window_end=_parse_iso(_iso("10:00")),
        duration=timedelta(minutes=30),
    )
    assert result is not None
    start, end = result
    assert (start.isoformat(), end.isoformat()) == (_iso("09:00"), _iso("09:30"))


def test_gap_before_busy_just_under_duration_falls_through_to_after() -> None:
    """29-min pre-gap is rejected; the slot after the busy block is returned."""
    result = first_free_slot(
        _busy(("09:29", "09:31")),
        window_start=_parse_iso(_iso("09:00")),
        window_end=_parse_iso(_iso("11:00")),
        duration=timedelta(minutes=30),
    )
    assert result is not None
    start, end = result
    assert (start.isoformat(), end.isoformat()) == (_iso("09:31"), _iso("10:01"))


def test_busy_fills_entire_window_returns_none() -> None:
    result = first_free_slot(
        _busy(("09:00", "10:00")),
        window_start=_parse_iso(_iso("09:00")),
        window_end=_parse_iso(_iso("10:00")),
        duration=timedelta(minutes=1),
    )
    assert result is None


def test_busy_starting_before_window_is_clamped_to_window() -> None:
    """A busy block overhanging the window start is clamped, not ignored:
    the slot must begin at the clamped end (09:30), never inside busy time."""
    result = first_free_slot(
        _busy(("08:00", "09:30")),
        window_start=_parse_iso(_iso("09:00")),
        window_end=_parse_iso(_iso("10:00")),
        duration=timedelta(minutes=30),
    )
    assert result is not None
    start, end = result
    assert (start.isoformat(), end.isoformat()) == (_iso("09:30"), _iso("10:00"))


def test_busy_entirely_outside_window_is_filtered_out() -> None:
    """Busy blocks wholly before or after the window do not consume it."""
    result = first_free_slot(
        _busy(("07:00", "08:00"), ("11:00", "12:00")),
        window_start=_parse_iso(_iso("09:00")),
        window_end=_parse_iso(_iso("10:00")),
        duration=timedelta(minutes=30),
    )
    assert result is not None
    start, end = result
    assert (start.isoformat(), end.isoformat()) == (_iso("09:00"), _iso("09:30"))


def test_overlapping_busy_blocks_merge_via_max_cursor() -> None:
    """Two overlapping busy blocks are merged: the cursor advances to the
    LATER end (11:00), so the slot lands after both, never between them."""
    result = first_free_slot(
        _busy(("09:00", "10:30"), ("10:00", "11:00")),
        window_start=_parse_iso(_iso("09:00")),
        window_end=_parse_iso(_iso("12:00")),
        duration=timedelta(minutes=60),
    )
    assert result is not None
    start, end = result
    assert (start.isoformat(), end.isoformat()) == (_iso("11:00"), _iso("12:00"))


# --------------------------------------------------------------------------
# Params validation: ISO fields + ordered window (fail closed)
# --------------------------------------------------------------------------


def test_params_reject_non_iso_window_start() -> None:
    with pytest.raises(ValidationError):
        CalendarFindFreeSlotParams(
            duration_minutes=30,
            window_start_iso="not-a-datetime",
            window_end_iso=_iso("10:00"),
        )


def test_params_reject_window_end_equal_to_start() -> None:
    """Boundary: end == start is NOT ordered — a zero-width window refuses."""
    with pytest.raises(ValidationError, match="after its start"):
        CalendarFindFreeSlotParams(
            duration_minutes=30,
            window_start_iso=_iso("09:00"),
            window_end_iso=_iso("09:00"),
        )


def test_params_reject_reversed_window() -> None:
    with pytest.raises(ValidationError, match="after its start"):
        CalendarFindFreeSlotParams(
            duration_minutes=30,
            window_start_iso=_iso("10:00"),
            window_end_iso=_iso("09:00"),
        )


def test_valid_params_round_trip_fields() -> None:
    params = CalendarFindFreeSlotParams(
        duration_minutes=45,
        window_start_iso=_iso("09:00"),
        window_end_iso=_iso("17:00"),
        description="1:1 with Sam",
    )
    assert params.duration_minutes == 45
    assert params.description == "1:1 with Sam"


# --------------------------------------------------------------------------
# _narrow + dry_run + execute (tool wrapper)
# --------------------------------------------------------------------------


def test_narrow_refuses_foreign_params_type() -> None:
    foreign = ContactsUpsertParams(name="Nobody")
    with pytest.raises(ToolExecutionError, match="expected CalendarFindFreeSlotParams"):
        _narrow(foreign)


def test_dry_run_includes_description_line_when_present() -> None:
    tool = CalendarFindFreeSlotTool()
    lines = tool.dry_run(
        CalendarFindFreeSlotParams(
            duration_minutes=30,
            window_start_iso=_iso("09:00"),
            window_end_iso=_iso("17:00"),
            description="quarterly review",
        )
    )
    assert lines == (
        "Find 30 min free",
        f"Between {_iso('09:00')} and {_iso('17:00')}",
        "For: quarterly review",
    )


def test_dry_run_omits_description_line_when_blank() -> None:
    tool = CalendarFindFreeSlotTool()
    lines = tool.dry_run(
        CalendarFindFreeSlotParams(
            duration_minutes=30,
            window_start_iso=_iso("09:00"),
            window_end_iso=_iso("17:00"),
        )
    )
    assert lines == (
        "Find 30 min free",
        f"Between {_iso('09:00')} and {_iso('17:00')}",
    )


async def test_execute_reports_exact_free_slot() -> None:
    session = FakeGoogleSession([{"calendars": {"primary": {"busy": []}}}])
    tool = CalendarFindFreeSlotTool()
    result = await tool.execute(
        CalendarFindFreeSlotParams(
            duration_minutes=30,
            window_start_iso=_iso("09:00"),
            window_end_iso=_iso("17:00"),
        ),
        session,
    )
    assert result.detail["slot_found"] is True
    assert result.detail["slot_start_iso"] == _iso("09:00")
    assert result.detail["slot_end_iso"] == _iso("09:30")
    assert result.summary_line == f"Free slot: {_iso('09:00')} to {_iso('09:30')}"


async def test_execute_reports_no_slot_when_calendar_is_full() -> None:
    session = FakeGoogleSession(
        [{"calendars": {"primary": {"busy": [{"start": _iso("09:00"), "end": _iso("17:00")}]}}}]
    )
    tool = CalendarFindFreeSlotTool()
    result = await tool.execute(
        CalendarFindFreeSlotParams(
            duration_minutes=30,
            window_start_iso=_iso("09:00"),
            window_end_iso=_iso("17:00"),
        ),
        session,
    )
    assert result.detail == {"slot_found": False, "busy_intervals": 1}
    assert result.summary_line == (
        f"No free 30 min slot between {_iso('09:00')} and {_iso('17:00')}"
    )


# --------------------------------------------------------------------------
# map_card_payload_to_tool_params: deterministic translation, per card type
# --------------------------------------------------------------------------


def test_create_event_maps_with_explicit_iso_and_filters_bare_names() -> None:
    outcome = map_card_payload_to_tool_params(
        CreateEventCardPayload(
            title="Design sync",
            start_iso=_iso("09:00"),
            end_iso=_iso("10:00"),
            attendees=["sam@nw.io", "Bare Name", "lee@nw.io"],
            description="agenda",
        )
    )
    assert outcome.is_deterministic
    assert isinstance(outcome.params, CalendarCreateEventParams)
    assert outcome.params.title == "Design sync"
    assert outcome.params.start_iso == _iso("09:00")
    # Bare names are dropped; only real addresses survive deterministically.
    assert outcome.params.attendee_emails == ["sam@nw.io", "lee@nw.io"]


def test_create_event_without_iso_is_ambiguous_and_carries_hint() -> None:
    outcome = map_card_payload_to_tool_params(
        CreateEventCardPayload(title="Lunch", when_hint="Friday at 1")
    )
    assert not outcome.is_deterministic
    assert outcome.params is None
    assert outcome.ambiguity_reason is not None
    assert "Friday at 1" in outcome.ambiguity_reason


def test_create_event_with_unordered_iso_fails_validation_to_ambiguous() -> None:
    """Explicit but invalid (end == start) must not map — it refuses honestly."""
    outcome = map_card_payload_to_tool_params(
        CreateEventCardPayload(
            title="Zero", start_iso=_iso("09:00"), end_iso=_iso("09:00")
        )
    )
    assert not outcome.is_deterministic
    assert outcome.ambiguity_reason is not None
    assert "did not validate" in outcome.ambiguity_reason


def test_find_slot_maps_explicit_window() -> None:
    outcome = map_card_payload_to_tool_params(
        FindSlotCardPayload(
            duration_minutes=30,
            window_start_iso=_iso("09:00"),
            window_end_iso=_iso("17:00"),
            description="call",
        )
    )
    assert isinstance(outcome.params, CalendarFindFreeSlotParams)
    assert outcome.params.duration_minutes == 30
    assert outcome.params.window_end_iso == _iso("17:00")


def test_find_slot_without_window_is_ambiguous() -> None:
    outcome = map_card_payload_to_tool_params(
        FindSlotCardPayload(duration_minutes=30)
    )
    assert not outcome.is_deterministic
    assert outcome.ambiguity_reason == "search window is not an explicit ISO start/end pair"


def test_find_slot_with_unordered_window_is_ambiguous() -> None:
    outcome = map_card_payload_to_tool_params(
        FindSlotCardPayload(
            duration_minutes=30,
            window_start_iso=_iso("10:00"),
            window_end_iso=_iso("09:00"),
        )
    )
    assert not outcome.is_deterministic
    assert outcome.ambiguity_reason is not None
    assert "did not validate" in outcome.ambiguity_reason


def test_upsert_contact_maps_one_to_one() -> None:
    outcome = map_card_payload_to_tool_params(
        UpsertContactCardPayload(
            name="Ana Cruz",
            phone="+44 20 7000 0000",
            email="ana@nw.io",
            company="Northwind",
            sync_to_google=True,
        )
    )
    assert isinstance(outcome.params, ContactsUpsertParams)
    assert outcome.params.name == "Ana Cruz"
    assert outcome.params.phone == "+44 20 7000 0000"
    assert outcome.params.email == "ana@nw.io"
    assert outcome.params.company == "Northwind"
    assert outcome.params.sync_to_google is True


def test_write_note_maps_title_and_body() -> None:
    outcome = map_card_payload_to_tool_params(
        WriteNoteCardPayload(title="Ideas", body_markdown="- ship it")
    )
    assert isinstance(outcome.params, VaultWriteNoteParams)
    assert outcome.params.title == "Ideas"
    assert outcome.params.body_markdown == "- ship it"


def test_draft_email_maps_addresses_and_defaults_subject() -> None:
    outcome = map_card_payload_to_tool_params(
        DraftEmailCardPayload(to=["sam@nw.io"], body_hint="hi")
    )
    assert isinstance(outcome.params, GmailCreateDraftParams)
    assert outcome.params.to == ["sam@nw.io"]
    assert outcome.params.subject == "(no subject)"  # None -> honest placeholder
    assert outcome.params.body_text == "hi"


def test_draft_email_with_bare_name_recipient_is_ambiguous() -> None:
    outcome = map_card_payload_to_tool_params(
        DraftEmailCardPayload(to=["Sam", "lee@nw.io"], subject="Terms")
    )
    assert not outcome.is_deterministic
    assert outcome.ambiguity_reason is not None
    assert "Sam" in outcome.ambiguity_reason


def test_draft_email_with_malformed_address_fails_validation_to_ambiguous() -> None:
    """'a@' contains '@' so passes the mapper's coarse filter, but the tool's
    own validator rejects it — mapping refuses rather than draft to junk."""
    outcome = map_card_payload_to_tool_params(
        DraftEmailCardPayload(to=["a@"], subject="Hi")
    )
    assert not outcome.is_deterministic
    assert outcome.ambiguity_reason is not None
    assert "did not validate" in outcome.ambiguity_reason
