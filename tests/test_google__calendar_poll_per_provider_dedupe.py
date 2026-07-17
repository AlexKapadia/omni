"""Calendar poll service: per-provider broadcast dedupe.

With both Google and Microsoft connected, a second poll tick must not
re-broadcast events already announced for either provider (the old shared
id set was overwritten by the Microsoft pass every tick).
"""

from __future__ import annotations

from datetime import UTC, datetime

from engine.google.calendar_poll_service import CalendarPollService
from engine.google.google_api_gateway import UpcomingCalendarEvent
from engine.google.google_session import GoogleSession
from engine.microsoft.graph_api_gateway import UpcomingOutlookEvent
from engine.microsoft.graph_session import MicrosoftSession
from engine.protocol import Envelope, EventBroadcastHub


class _FakeGoogleSession(GoogleSession):
    async def request_json(
        self,
        method: str,
        url: str,
        *,
        params: dict[str, str] | None = None,
        json_body: dict[str, object] | None = None,
    ) -> dict[str, object]:
        return {"items": []}


class _FakeMicrosoftSession(MicrosoftSession):
    async def request_json(
        self,
        method: str,
        url: str,
        *,
        params: dict[str, str] | None = None,
        json_body: dict[str, object] | None = None,
    ) -> dict[str, object]:
        return {"value": []}


async def test_both_providers_second_tick_re_broadcasts_nothing() -> None:
    hub = EventBroadcastHub()
    events: list[Envelope] = []

    async def collect(envelope: Envelope) -> None:
        events.append(envelope)

    hub.subscribe(collect)
    service = CalendarPollService(
        hub,
        session=_FakeGoogleSession(),
        microsoft_session=_FakeMicrosoftSession(),
        now_factory=lambda: datetime(2026, 7, 10, 12, 0, tzinfo=UTC),
    )

    google_events = (
        UpcomingCalendarEvent(
            event_id="g1",
            title="Google standup",
            start_iso="2026-07-10T12:05:00+00:00",
            end_iso="2026-07-10T12:30:00+00:00",
            attendee_emails=(),
        ),
    )
    outlook_events = (
        UpcomingOutlookEvent(
            event_id="o1",
            title="Outlook sync",
            start_iso="2026-07-10T12:10:00+00:00",
            end_iso="2026-07-10T12:40:00+00:00",
            attendee_emails=(),
        ),
    )

    await service._broadcast_new(google_events, provider="google")
    await service._broadcast_new(outlook_events, provider="outlook")
    assert len(events) == 2
    first_ids = {e.payload["event_id"] for e in events}
    assert first_ids == {"g1", "o1"}

    # Second tick with the same events: neither provider re-broadcasts.
    await service._broadcast_new(google_events, provider="google")
    await service._broadcast_new(outlook_events, provider="outlook")
    assert len(events) == 2
