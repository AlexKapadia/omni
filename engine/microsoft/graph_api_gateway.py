"""Microsoft Graph calendar helpers.

Security invariants:
- KILL SWITCH FIRST (fail closed): every function checks the global egress
  kill switch BEFORE touching the session, mirroring the Google gateway.
"""

from __future__ import annotations

from dataclasses import dataclass

from engine.microsoft.graph_session import MicrosoftSession
from engine.microsoft.microsoft_auth_errors import MicrosoftEgressBlockedError
from engine.security.kill_switch import kill_switch_engaged

GRAPH_BASE = "https://graph.microsoft.com/v1.0"


def _refuse_egress_when_kill_switch_engaged() -> None:
    """claude.md §5.6 kill switch: engaged means NO Graph call, period."""
    # kill-switch: refuse all egress when engaged
    if kill_switch_engaged():
        raise MicrosoftEgressBlockedError


@dataclass(frozen=True)
class UpcomingOutlookEvent:
    event_id: str
    title: str
    start_iso: str
    end_iso: str
    attendee_emails: tuple[str, ...]


async def list_upcoming_outlook_events(
    session: MicrosoftSession,
    *,
    time_min_iso: str,
    time_max_iso: str,
) -> tuple[UpcomingOutlookEvent, ...]:
    _refuse_egress_when_kill_switch_engaged()
    payload = await session.request_json(
        "GET",
        f"{GRAPH_BASE}/me/calendarView",
        params={
            "startDateTime": time_min_iso,
            "endDateTime": time_max_iso,
            "$select": "id,subject,start,end,attendees",
            "$orderby": "start/dateTime",
            "$top": "10",
        },
    )
    values = payload.get("value")
    if not isinstance(values, list):
        return ()
    events: list[UpcomingOutlookEvent] = []
    for item in values:
        if not isinstance(item, dict):
            continue
        event_id = str(item.get("id", ""))
        title = str(item.get("subject") or "Untitled meeting")
        start = item.get("start")
        end = item.get("end")
        start_iso = ""
        end_iso = ""
        if isinstance(start, dict):
            start_iso = str(start.get("dateTime") or start.get("date") or "")
        if isinstance(end, dict):
            end_iso = str(end.get("dateTime") or end.get("date") or "")
        attendees_raw = item.get("attendees")
        emails: list[str] = []
        if isinstance(attendees_raw, list):
            for attendee in attendees_raw:
                if not isinstance(attendee, dict):
                    continue
                email_address = attendee.get("emailAddress")
                if isinstance(email_address, dict):
                    address = email_address.get("address")
                    if isinstance(address, str) and address:
                        emails.append(address)
        if event_id and start_iso:
            events.append(
                UpcomingOutlookEvent(
                    event_id=event_id,
                    title=title,
                    start_iso=start_iso,
                    end_iso=end_iso or start_iso,
                    attendee_emails=tuple(emails),
                )
            )
    return tuple(events)
