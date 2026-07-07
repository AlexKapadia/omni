"""naomi.listen.start / naomi.listen.stop over the REAL WS surface (v1).

Drives the real app + connection handler with a FAKE turn control (no models,
no mic, no socket): strict payload validation (extra fields forbidden), an
honest ``naomi_loop_error`` when the loop is not wired, and correct delegation
of the open_mic / flush flags. The heavy real loop (models + Cartesia) is
exercised by the live probe, deliberately OUTSIDE this hermetic suite.
"""

import json
import uuid
from pathlib import Path
from typing import Any

import pytest
from starlette.testclient import TestClient, WebSocketTestSession

from engine.protocol import EventBroadcastHub
from engine.server import create_app
from engine.stt.live_capture_service import LiveCaptureService
from tests.conftest import receive_frame


class IdleCaptureService(LiveCaptureService):
    """No-hardware stand-in so create_app boots without audio/models."""

    def __init__(self, hub: EventBroadcastHub) -> None:
        super().__init__(db_path=Path("unused.db"), migrations_dir=Path("unused"), hub=hub)


class FakeTurnControl:
    """Satisfies NaomiTurnControl structurally; records the delegated flags."""

    def __init__(self) -> None:
        self.starts: list[bool] = []
        self.stops: list[bool] = []
        self._state = "idle"

    async def listen_start(self, open_mic: bool) -> None:
        self.starts.append(open_mic)
        self._state = "listening"

    async def listen_stop(self, flush: bool) -> None:
        self.stops.append(flush)
        self._state = "idle"

    async def shutdown(self) -> None:
        return None

    @property
    def state(self) -> str:
        return self._state


def _app_with_loop() -> Any:
    return create_app(
        capture_service_factory=IdleCaptureService,
        naomi_loop_gateway_factory=lambda _hub: FakeTurnControl(),
    )


def _app_without_loop() -> Any:
    return create_app(capture_service_factory=IdleCaptureService)


def _command(name: str, payload: dict[str, Any], command_id: str | None = None) -> str:
    return json.dumps(
        {
            "v": 1,
            "kind": "command",
            "name": name,
            "id": command_id or str(uuid.uuid4()),
            "payload": payload,
        }
    )


def _reply(ws: WebSocketTestSession, limit: int = 20) -> dict[str, Any]:
    for _ in range(limit):
        frame = receive_frame(ws)
        if frame["kind"] == "reply":
            return frame
    raise AssertionError("no reply received")


def test_listen_start_and_stop_reply_ok_with_state() -> None:
    app = _app_with_loop()
    with TestClient(app) as client, client.websocket_connect("/ws") as ws:
        ws.send_text(_command("naomi.listen.start", {"open_mic": True}, "s1"))
        reply = _reply(ws)
        assert reply["name"] == "ok" and reply["id"] == "s1"
        assert reply["payload"]["state"] == "listening"
        ws.send_text(_command("naomi.listen.stop", {"flush": True}, "s2"))
        reply = _reply(ws)
        assert reply["name"] == "ok" and reply["payload"]["state"] == "idle"


def test_listen_start_defaults_open_mic_false() -> None:
    app = _app_with_loop()
    with TestClient(app) as client, client.websocket_connect("/ws") as ws:
        # Empty payload is legal: open_mic defaults to False (push-to-talk).
        ws.send_text(_command("naomi.listen.start", {}, "s3"))
        assert _reply(ws)["name"] == "ok"


def test_loop_not_wired_is_an_honest_error_not_a_crash() -> None:
    app = _app_without_loop()
    with TestClient(app) as client, client.websocket_connect("/ws") as ws:
        ws.send_text(_command("naomi.listen.start", {"open_mic": True}, "s4"))
        reply = _reply(ws)
        assert reply["name"] == "error"
        assert reply["payload"]["code"] == "naomi_loop_error"
        # The socket survives: ping still answers.
        ws.send_text(_command("ping", {}, "p"))
        assert _reply(ws)["name"] == "pong"


@pytest.mark.parametrize(
    "payload",
    [
        {"open_mic": "maybe"},  # not a coercible bool
        {"open_mic": True, "extra": 1},  # unknown field: deny by default
        {"open_mic": [1]},  # list is not a bool
        {"open_mic": 2},  # int outside {0, 1} is not a bool
    ],
)
def test_malformed_listen_start_gets_invalid_payload(payload: dict[str, Any]) -> None:
    app = _app_with_loop()
    with TestClient(app) as client, client.websocket_connect("/ws") as ws:
        ws.send_text(_command("naomi.listen.start", payload, "bad"))
        reply = _reply(ws)
        assert reply["name"] == "error"
        assert reply["payload"]["code"] == "invalid_payload"


def test_malformed_listen_stop_gets_invalid_payload() -> None:
    app = _app_with_loop()
    with TestClient(app) as client, client.websocket_connect("/ws") as ws:
        ws.send_text(_command("naomi.listen.stop", {"flush": "nope", "x": 2}, "bad2"))
        reply = _reply(ws)
        assert reply["payload"]["code"] == "invalid_payload"
