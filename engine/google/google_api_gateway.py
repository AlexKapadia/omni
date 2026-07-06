"""Thin typed wrappers over the three Google REST APIs (the only egress).

Purpose: every Google call the engine can make, as a small set of typed
functions over plain REST via the injected :class:`GoogleSession` — no
heavy ``google-api-python-client`` (rationale logged in
``docs/progress/pending-deps.txt``). Request building and response parsing
are pure and fully testable against a fake session.
Pipeline position: called ONLY by the agent tools; sits on
``google_session`` below.

Security invariants:
- KILL SWITCH FIRST (fail closed): every function checks the global egress
  kill switch BEFORE touching the session, mirroring the router. Local
  vault tools never route through here and keep working with it engaged.
- DRAFT-ONLY (binding): the Gmail surface is exactly ONE function that
  creates a draft. No function here — or anywhere in the engine — can
  dispatch mail; the capability simply does not exist in code.
- Responses are parsed fail-closed: a missing id/field is a typed
  ``GoogleApiCallError``, never a half-populated result.
"""

import base64
from dataclasses import dataclass
from email.message import EmailMessage

from engine.google.google_auth_errors import GoogleApiCallError, GoogleEgressBlockedError
from engine.google.google_session import GoogleSession
from engine.security.kill_switch import kill_switch_engaged

CALENDAR_EVENTS_URL = "https://www.googleapis.com/calendar/v3/calendars/{calendar_id}/events"
CALENDAR_FREEBUSY_URL = "https://www.googleapis.com/calendar/v3/freeBusy"
PEOPLE_CREATE_CONTACT_URL = "https://people.googleapis.com/v1/people:createContact"
GMAIL_CREATE_DRAFT_URL = "https://gmail.googleapis.com/gmail/v1/users/me/drafts"


def _refuse_egress_when_kill_switch_engaged() -> None:
    """claude.md §5.6 kill switch: engaged means NO Google call, period."""
    if kill_switch_engaged():
        raise GoogleEgressBlockedError


@dataclass(frozen=True)
class CreatedCalendarEvent:
    event_id: str
    html_link: str


@dataclass(frozen=True)
class BusyInterval:
    start_iso: str
    end_iso: str


@dataclass(frozen=True)
class CreatedGoogleContact:
    resource_name: str


@dataclass(frozen=True)
class CreatedGmailDraft:
    draft_id: str
    message_id: str


async def create_calendar_event(
    session: GoogleSession,
    *,
    title: str,
    start_iso: str,
    end_iso: str,
    description: str = "",
    attendee_emails: tuple[str, ...] = (),
    calendar_id: str = "primary",
) -> CreatedCalendarEvent:
    """Insert one event on the user's calendar (scope: calendar.events)."""
    _refuse_egress_when_kill_switch_engaged()
    body: dict[str, object] = {
        "summary": title,
        "start": {"dateTime": start_iso},
        "end": {"dateTime": end_iso},
    }
    if description:
        body["description"] = description
    if attendee_emails:
        body["attendees"] = [{"email": email} for email in attendee_emails]
    response = await session.request_json(
        "POST", CALENDAR_EVENTS_URL.format(calendar_id=calendar_id), json_body=body
    )
    event_id = response.get("id")
    if not isinstance(event_id, str) or not event_id:
        raise GoogleApiCallError("Calendar", None, "created event carried no id")
    html_link = response.get("htmlLink")
    return CreatedCalendarEvent(
        event_id=event_id, html_link=html_link if isinstance(html_link, str) else ""
    )


async def query_free_busy(
    session: GoogleSession,
    *,
    time_min_iso: str,
    time_max_iso: str,
    calendar_id: str = "primary",
) -> tuple[BusyInterval, ...]:
    """The busy intervals on one calendar inside a window (read-only)."""
    _refuse_egress_when_kill_switch_engaged()
    response = await session.request_json(
        "POST",
        CALENDAR_FREEBUSY_URL,
        json_body={
            "timeMin": time_min_iso,
            "timeMax": time_max_iso,
            "items": [{"id": calendar_id}],
        },
    )
    calendars = response.get("calendars")
    if not isinstance(calendars, dict):
        raise GoogleApiCallError("Calendar freeBusy", None, "response carried no calendars")
    entry = calendars.get(calendar_id)
    if not isinstance(entry, dict):
        raise GoogleApiCallError("Calendar freeBusy", None, "calendar missing from response")
    busy_raw = entry.get("busy", [])
    if not isinstance(busy_raw, list):
        raise GoogleApiCallError("Calendar freeBusy", None, "busy list malformed")
    intervals: list[BusyInterval] = []
    for item in busy_raw:
        if (
            not isinstance(item, dict)
            or not isinstance(item.get("start"), str)
            or not isinstance(item.get("end"), str)
        ):
            # fail-closed: one malformed interval poisons the whole answer —
            # a slot proposed over unseen busy time would double-book.
            raise GoogleApiCallError("Calendar freeBusy", None, "busy interval malformed")
        intervals.append(BusyInterval(start_iso=item["start"], end_iso=item["end"]))
    return tuple(intervals)


async def create_google_contact(
    session: GoogleSession,
    *,
    name: str,
    email: str | None = None,
    phone: str | None = None,
    company: str | None = None,
) -> CreatedGoogleContact:
    """Create one People contact (scope: contacts)."""
    _refuse_egress_when_kill_switch_engaged()
    body: dict[str, object] = {"names": [{"unstructuredName": name}]}
    if email:
        body["emailAddresses"] = [{"value": email}]
    if phone:
        body["phoneNumbers"] = [{"value": phone}]
    if company:
        body["organizations"] = [{"name": company}]
    response = await session.request_json("POST", PEOPLE_CREATE_CONTACT_URL, json_body=body)
    resource_name = response.get("resourceName")
    if not isinstance(resource_name, str) or not resource_name:
        raise GoogleApiCallError("People", None, "created contact carried no resourceName")
    return CreatedGoogleContact(resource_name=resource_name)


def build_draft_raw_mime(to: tuple[str, ...], subject: str, body_text: str) -> str:
    """RFC-822 message as base64url — the Gmail draft wire format.

    Pure and exact (unit-tested by decoding): recipients on ``To``, UTF-8
    text body, no other headers invented.
    """
    message = EmailMessage()
    if to:
        message["To"] = ", ".join(to)
    message["Subject"] = subject
    message.set_content(body_text)
    return base64.urlsafe_b64encode(message.as_bytes()).decode("ascii")


async def create_gmail_draft(
    session: GoogleSession,
    *,
    to: tuple[str, ...],
    subject: str,
    body_text: str,
) -> CreatedGmailDraft:
    """Create one Gmail DRAFT (scope: gmail.compose).

    DRAFT-ONLY INVARIANT (binding, claude.md §5.6): this is the entire Gmail
    write surface. The engine has no code path that dispatches mail — the
    user reviews and acts on the draft in Gmail themselves.
    """
    _refuse_egress_when_kill_switch_engaged()
    response = await session.request_json(
        "POST",
        GMAIL_CREATE_DRAFT_URL,
        json_body={"message": {"raw": build_draft_raw_mime(to, subject, body_text)}},
    )
    draft_id = response.get("id")
    if not isinstance(draft_id, str) or not draft_id:
        raise GoogleApiCallError("Gmail", None, "created draft carried no id")
    message = response.get("message")
    message_id = message.get("id") if isinstance(message, dict) else None
    return CreatedGmailDraft(
        draft_id=draft_id, message_id=message_id if isinstance(message_id, str) else ""
    )
