"""WS capture command surface: capture.start / capture.stop over protocol v1.

Drives the REAL app + connection handler with an injected fake capture
service (no audio hardware, no models): replies must correlate by id,
failures must map to the pinned error codes, events must fan out to the
socket, and the heartbeat must report the service's real stt_ready.
"""

import json
import uuid
from pathlib import Path
from typing import Any

from starlette.testclient import TestClient, WebSocketTestSession

from engine.protocol import EventBroadcastHub, build_capture_started_payload
from engine.server import create_app
from engine.stt.live_capture_service import CaptureServiceError, LiveCaptureService
from tests.conftest import receive_frame


class FakeCaptureService(LiveCaptureService):
    """State-machine stub: real start/stop semantics, no hardware."""

    def __init__(self, hub: EventBroadcastHub) -> None:
        super().__init__(
            db_path=Path("unused.db"), migrations_dir=Path("unused"), hub=hub
        )
        self.running_meeting: str | None = None
        self.titles_seen: list[str | None] = []

    @property
    def is_stt_ready(self) -> bool:
        return True  # Models "loaded": heartbeat must reflect this.

    async def start(self, title: str | None) -> str:
        if self.running_meeting is not None:
            raise CaptureServiceError("capture is already running")
        self.titles_seen.append(title)
        self.running_meeting = f"meeting-{uuid.uuid4()}"
        await self._hub.broadcast_event(
            "capture.started", build_capture_started_payload(self.running_meeting, "command")
        )
        return self.running_meeting

    async def stop(self, reason: str = "command") -> str:
        if self.running_meeting is None:
            raise CaptureServiceError("capture is not running")
        stopped, self.running_meeting = self.running_meeting, None
        return stopped


def make_app_and_service() -> tuple[Any, list[FakeCaptureService]]:
    created: list[FakeCaptureService] = []

    def factory(hub: EventBroadcastHub) -> LiveCaptureService:
        service = FakeCaptureService(hub)
        created.append(service)
        return service

    return create_app(capture_service_factory=factory), created


def command(name: str, payload: dict[str, Any], command_id: str | None = None) -> str:
    return json.dumps(
        {
            "v": 1,
            "kind": "command",
            "name": name,
            "id": command_id or str(uuid.uuid4()),
            "payload": payload,
        }
    )


def collect_until_reply(ws: WebSocketTestSession, limit: int = 20) -> list[dict[str, Any]]:
    """Read frames (skipping heartbeats) until a reply arrives; return all."""
    frames: list[dict[str, Any]] = []
    for _ in range(limit):
        frame = receive_frame(ws)
        if frame.get("name") == "engine.heartbeat":
            continue
        frames.append(frame)
        if frame["kind"] == "reply":
            return frames
    raise AssertionError(f"no reply within {limit} frames: {frames}")


def test_heartbeat_reports_the_capture_services_real_stt_readiness() -> None:
    app, _ = make_app_and_service()
    with TestClient(app) as client, client.websocket_connect("/ws") as ws:
        heartbeat = receive_frame(ws)
        assert heartbeat["name"] == "engine.heartbeat"
        assert heartbeat["payload"]["stt_ready"] is True  # Flipped from M0's False.


def test_capture_start_replies_ok_with_meeting_id_and_broadcasts_started() -> None:
    app, services = make_app_and_service()
    with TestClient(app) as client, client.websocket_connect("/ws") as ws:
        command_id = f"start-{uuid.uuid4()}"
        ws.send_text(command("capture.start", {"title": "Standup"}, command_id))
        frames = collect_until_reply(ws)
    reply = frames[-1]
    assert reply["kind"] == "reply" and reply["name"] == "ok"
    assert reply["id"] == command_id  # Correlation contract.
    assert reply["payload"]["meeting_id"] == services[0].running_meeting
    assert services[0].titles_seen == ["Standup"]
    # The capture.started event reached this socket too (hub fan-out).
    events = [f for f in frames if f["kind"] == "event" and f["name"] == "capture.started"]
    assert len(events) == 1
    assert events[0]["payload"]["reason"] == "command"


def test_second_capture_start_gets_capture_error_not_a_second_session() -> None:
    app, services = make_app_and_service()
    with TestClient(app) as client, client.websocket_connect("/ws") as ws:
        ws.send_text(command("capture.start", {}))
        collect_until_reply(ws)
        first_meeting = services[0].running_meeting
        ws.send_text(command("capture.start", {}, "dup-start"))
        frames = collect_until_reply(ws)
    reply = frames[-1]
    assert reply["name"] == "error"
    assert reply["id"] == "dup-start"
    assert reply["payload"]["code"] == "capture_error"
    assert services[0].running_meeting == first_meeting  # Unchanged.


def test_capture_stop_replies_ok_and_stop_without_start_is_an_error() -> None:
    app, services = make_app_and_service()
    with TestClient(app) as client, client.websocket_connect("/ws") as ws:
        ws.send_text(command("capture.stop", {}, "premature"))
        frames = collect_until_reply(ws)
        assert frames[-1]["payload"]["code"] == "capture_error"

        ws.send_text(command("capture.start", {}))
        collect_until_reply(ws)
        meeting_id = services[0].running_meeting
        ws.send_text(command("capture.stop", {}, "stop-1"))
        frames = collect_until_reply(ws)
    reply = frames[-1]
    assert reply["name"] == "ok" and reply["id"] == "stop-1"
    assert reply["payload"]["meeting_id"] == meeting_id
    assert services[0].running_meeting is None


def test_malformed_capture_payloads_get_invalid_payload_and_start_nothing() -> None:
    app, services = make_app_and_service()
    hostile_payloads: list[dict[str, Any]] = [
        {"title": 123},  # Wrong type.
        {"title": "x" * 513},  # Over the length bound.
        {"unexpected": "field"},  # Unknown field: deny by default.
        {"title": "ok", "extra": 1},
    ]
    with TestClient(app) as client, client.websocket_connect("/ws") as ws:
        for payload in hostile_payloads:
            ws.send_text(command("capture.start", payload, "bad"))
            frames = collect_until_reply(ws)
            assert frames[-1]["payload"]["code"] == "invalid_payload"
        ws.send_text(command("capture.stop", {"extra": True}, "bad-stop"))
        frames = collect_until_reply(ws)
        assert frames[-1]["payload"]["code"] == "invalid_payload"
    assert services[0].running_meeting is None  # Nothing ever started.
    assert services[0].titles_seen == []


def test_capture_events_fan_out_to_every_connected_socket() -> None:
    """Two UI windows: both must see capture.started, only the sender
    gets the reply."""
    app, _ = make_app_and_service()
    with (
        TestClient(app) as client,
        client.websocket_connect("/ws") as ws_a,
        client.websocket_connect("/ws") as ws_b,
    ):
        ws_a.send_text(command("capture.start", {}))
        frames_a = collect_until_reply(ws_a)
        assert any(f["name"] == "capture.started" for f in frames_a)
        # The passive socket receives the event too (skip its heartbeats).
        for _ in range(10):
            frame = receive_frame(ws_b)
            if frame["name"] == "capture.started":
                break
        else:
            raise AssertionError("second socket never saw capture.started")
