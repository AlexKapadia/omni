"""Kill-switch egress tests: engaged means NO Microsoft Graph call.

Mirrors ``test_agents__kill_switch_blocks_google_calls``: every Graph
surface must refuse BEFORE touching the session / network so with the
switch engaged the fake session records zero requests.
"""

from __future__ import annotations

import pytest

from engine.microsoft.graph_api_gateway import list_upcoming_outlook_events
from engine.microsoft.graph_session import MicrosoftSession
from engine.microsoft.microsoft_auth_errors import MicrosoftEgressBlockedError
from engine.microsoft.oauth_desktop_flow import run_microsoft_oauth_desktop_flow
from engine.security.kill_switch import set_kill_switch_runtime_override


class FakeMicrosoftSession(MicrosoftSession):
    """Records request_json calls; never touches the network."""

    def __init__(self, payload: dict[str, object] | None = None) -> None:
        self.requests: list[tuple[str, str]] = []
        self._payload = payload if payload is not None else {"value": []}

    async def request_json(
        self,
        method: str,
        url: str,
        *,
        params: dict[str, str] | None = None,
        json_body: dict[str, object] | None = None,
    ) -> dict[str, object]:
        self.requests.append((method, url))
        return dict(self._payload)


@pytest.fixture()
def engaged_kill_switch():  # type: ignore[no-untyped-def]
    """Engage via the runtime override (beats env), restore afterwards."""
    set_kill_switch_runtime_override(True)
    try:
        yield
    finally:
        set_kill_switch_runtime_override(None)


async def test_list_upcoming_outlook_events_refused_before_any_session_touch(
    engaged_kill_switch: None,
) -> None:
    session = FakeMicrosoftSession()
    with pytest.raises(MicrosoftEgressBlockedError):
        await list_upcoming_outlook_events(
            session,
            time_min_iso="2026-07-10T09:00:00+00:00",
            time_max_iso="2026-07-10T18:00:00+00:00",
        )
    assert session.requests == []  # refused BEFORE egress, not after


async def test_request_json_refused_when_kill_switch_engaged(
    engaged_kill_switch: None,
) -> None:
    """DpapiMicrosoftSession.request_json itself fails closed on the switch."""
    from engine.microsoft.graph_session import DpapiMicrosoftSession

    session = DpapiMicrosoftSession()
    with pytest.raises(MicrosoftEgressBlockedError):
        await session.request_json("GET", "https://graph.microsoft.com/v1.0/me")


async def test_oauth_desktop_flow_refused_when_kill_switch_engaged(
    engaged_kill_switch: None,
) -> None:
    from engine.microsoft.dpapi_microsoft_token_store import MicrosoftTokenStore

    with pytest.raises(MicrosoftEgressBlockedError):
        await run_microsoft_oauth_desktop_flow(MicrosoftTokenStore())


async def test_disengaging_the_switch_lets_graph_calls_through_again() -> None:
    """The refusal is the switch, not a latch: off means calls flow."""
    set_kill_switch_runtime_override(True)
    session = FakeMicrosoftSession(
        {
            "value": [
                {
                    "id": "evt-1",
                    "subject": "Standup",
                    "start": {"dateTime": "2026-07-10T13:00:00"},
                    "end": {"dateTime": "2026-07-10T13:30:00"},
                    "attendees": [],
                }
            ]
        }
    )
    try:
        with pytest.raises(MicrosoftEgressBlockedError):
            await list_upcoming_outlook_events(
                session,
                time_min_iso="2026-07-10T09:00:00+00:00",
                time_max_iso="2026-07-10T18:00:00+00:00",
            )
    finally:
        set_kill_switch_runtime_override(False)
    try:
        events = await list_upcoming_outlook_events(
            session,
            time_min_iso="2026-07-10T09:00:00+00:00",
            time_max_iso="2026-07-10T18:00:00+00:00",
        )
        assert len(events) == 1
        assert events[0].event_id == "evt-1"
        assert len(session.requests) == 1
    finally:
        set_kill_switch_runtime_override(None)
