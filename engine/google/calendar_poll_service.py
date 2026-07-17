"""Poll Google Calendar for meetings starting soon and broadcast context.

Runs only when Google is connected; fails closed silently when not.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from engine.google.google_api_gateway import UpcomingCalendarEvent, list_upcoming_calendar_events
from engine.google.google_auth_errors import GoogleNotConnectedError
from engine.google.google_session import DpapiGoogleSession, GoogleSession
from engine.microsoft.graph_api_gateway import UpcomingOutlookEvent, list_upcoming_outlook_events
from engine.microsoft.graph_session import DpapiMicrosoftSession, MicrosoftSession
from engine.microsoft.microsoft_auth_errors import MicrosoftNotConnectedError
from engine.protocol.calendar_event_payloads import (
    EVENT_CALENDAR_UPCOMING,
    build_calendar_upcoming_payload,
)
from engine.protocol.event_broadcast_hub import EventBroadcastHub

logger = logging.getLogger(__name__)

POLL_INTERVAL_S = 300.0
LOOKAHEAD_MINUTES = 5


class CalendarPollService:
    """Background poll loop for upcoming calendar events."""

    def __init__(
        self,
        hub: EventBroadcastHub,
        session: GoogleSession | None = None,
        microsoft_session: MicrosoftSession | None = None,
        poll_interval_s: float = POLL_INTERVAL_S,
        lookahead_minutes: int = LOOKAHEAD_MINUTES,
        now_factory: Callable[[], datetime] | None = None,
    ) -> None:
        self._hub = hub
        self._session = session if session is not None else DpapiGoogleSession()
        self._microsoft_session = (
            microsoft_session if microsoft_session is not None else DpapiMicrosoftSession()
        )
        self._poll_interval_s = poll_interval_s
        self._lookahead = timedelta(minutes=lookahead_minutes)
        self._now_factory = now_factory or (lambda: datetime.now(tz=UTC))
        self._task: asyncio.Task[None] | None = None
        self._last_broadcast_ids: frozenset[str] = frozenset()

    def start(self) -> None:
        if self._task is not None and not self._task.done():
            return
        self._task = asyncio.get_running_loop().create_task(
            self._run_loop(), name="calendar-poll-loop"
        )

    async def stop(self) -> None:
        task, self._task = self._task, None
        if task is None or task.done():
            return
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

    async def _run_loop(self) -> None:
        while True:
            await self._tick()
            await asyncio.sleep(self._poll_interval_s)

    async def _tick(self) -> None:
        now = self._now_factory()
        window_end = now + self._lookahead
        time_min_iso = now.isoformat()
        time_max_iso = window_end.isoformat()
        await self._poll_google(time_min_iso, time_max_iso)
        await self._poll_microsoft(time_min_iso, time_max_iso)

    async def _poll_google(self, time_min_iso: str, time_max_iso: str) -> None:
        try:
            events = await list_upcoming_calendar_events(
                self._session,
                time_min_iso=time_min_iso,
                time_max_iso=time_max_iso,
            )
        except GoogleNotConnectedError:
            return
        except Exception:
            logger.exception("google calendar poll tick failed; skipping")
            return
        await self._broadcast_new(events, provider="google")

    async def _poll_microsoft(self, time_min_iso: str, time_max_iso: str) -> None:
        try:
            events = await list_upcoming_outlook_events(
                self._microsoft_session,
                time_min_iso=time_min_iso,
                time_max_iso=time_max_iso,
            )
        except MicrosoftNotConnectedError:
            return
        except Exception:
            logger.exception("outlook calendar poll tick failed; skipping")
            return
        await self._broadcast_new(events, provider="outlook")

    async def _broadcast_new(
        self,
        events: tuple[UpcomingCalendarEvent, ...] | tuple[UpcomingOutlookEvent, ...],
        provider: str,
    ) -> None:
        current_ids = frozenset(f"{provider}:{event.event_id}" for event in events)
        for event in events:
            key = f"{provider}:{event.event_id}"
            if key in self._last_broadcast_ids:
                continue
            payload = build_calendar_upcoming_payload(
                event_id=event.event_id,
                title=event.title,
                start_iso=event.start_iso,
                end_iso=event.end_iso,
                attendee_emails=event.attendee_emails,
                provider=provider,
            )
            try:
                await self._hub.broadcast_event(EVENT_CALENDAR_UPCOMING, payload)
            except Exception:
                logger.exception("calendar.upcoming broadcast failed")
        self._last_broadcast_ids = current_ids
