"""Tests for listing upcoming Google Calendar events."""

from __future__ import annotations

import pytest

from engine.google.google_api_gateway import UpcomingCalendarEvent, list_upcoming_calendar_events
from engine.google.google_session import GoogleSession


class _FakeSession(GoogleSession):
    def __init__(self, response: dict[str, object]) -> None:
        self._response = response
        self.last_params: dict[str, str] | None = None

    async def request_json(
        self,
        method: str,
        url: str,
        *,
        params: dict[str, str] | None = None,
        json_body: dict[str, object] | None = None,
    ) -> dict[str, object]:
        assert method == "GET"
        self.last_params = params
        return self._response


@pytest.mark.asyncio
async def test_list_upcoming_calendar_events_parses_items() -> None:
    session = _FakeSession(
        {
            "items": [
                {
                    "id": "evt-1",
                    "summary": "Standup",
                    "start": {"dateTime": "2026-07-08T10:00:00Z"},
                    "end": {"dateTime": "2026-07-08T10:15:00Z"},
                    "attendees": [{"email": "alice@example.com"}],
                }
            ]
        }
    )
    events = await list_upcoming_calendar_events(
        session,
        time_min_iso="2026-07-08T09:00:00Z",
        time_max_iso="2026-07-08T11:00:00Z",
    )
    assert events == (
        UpcomingCalendarEvent(
            event_id="evt-1",
            title="Standup",
            start_iso="2026-07-08T10:00:00Z",
            end_iso="2026-07-08T10:15:00Z",
            attendee_emails=("alice@example.com",),
        ),
    )
    assert session.last_params is not None
    assert session.last_params["singleEvents"] == "true"
