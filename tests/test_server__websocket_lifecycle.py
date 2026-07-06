"""Live WS lifecycle tests against the real app, in-process (no network).

Starlette's TestClient drives the actual FastAPI app and WebSocket route:
connect → heartbeat arrives → ping/pong id correlation → unknown command
and malformed frames answered with errors — and the socket survives all of
it (fail closed, stay up).
"""

import json
import math
import time
import uuid
from typing import Any

from starlette.testclient import TestClient

from engine import ENGINE_VERSION
from engine.server import create_app
from tests.conftest import receive_frame, receive_non_heartbeat_frame


def _command(name: str, command_id: str | None = None) -> str:
    return json.dumps(
        {
            "v": 1,
            "kind": "command",
            "name": name,
            "id": command_id or str(uuid.uuid4()),
            "payload": {},
        }
    )


def _assert_error_reply(frame: dict[str, Any], expected_code: str) -> None:
    """Error replies have the pinned shape: reply/error + code + message."""
    assert frame["v"] == 1
    assert frame["kind"] == "reply"
    assert frame["name"] == "error"
    assert frame["payload"]["code"] == expected_code
    assert isinstance(frame["payload"]["message"], str) and frame["payload"]["message"]


def test_health_endpoint_reports_ok_and_the_engine_version() -> None:
    with TestClient(create_app()) as client:
        response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "version": ENGINE_VERSION}


def test_connect_receives_a_heartbeat_with_the_pinned_payload_shape() -> None:
    with TestClient(create_app()) as client, client.websocket_connect("/ws") as ws:
        frame = receive_frame(ws)
        assert frame["v"] == 1
        assert frame["kind"] == "event"
        assert frame["name"] == "engine.heartbeat"
        payload = frame["payload"]
        # Exact pinned key set — extra or missing keys break the UI contract.
        assert set(payload.keys()) == {"uptime_s", "engine_version", "python", "stt_ready"}
        assert isinstance(payload["uptime_s"], float)
        assert payload["uptime_s"] >= 0.0 and math.isfinite(payload["uptime_s"])
        assert payload["engine_version"] == ENGINE_VERSION
        assert isinstance(payload["python"], str) and payload["python"].startswith("3.")
        assert payload["stt_ready"] is False  # honest: no STT stack in M0


def test_ping_gets_a_pong_carrying_the_same_id_and_a_sane_timestamp() -> None:
    with TestClient(create_app()) as client, client.websocket_connect("/ws") as ws:
        ping_id = f"ping-{uuid.uuid4()}"
        before = time.time()
        ws.send_text(_command("ping", ping_id))
        pong = receive_non_heartbeat_frame(ws)
        after = time.time()
    assert pong["kind"] == "reply"
    assert pong["name"] == "pong"
    assert pong["id"] == ping_id  # contract: reply id == command id
    # ts is a real wall-clock float bracketed by the request window.
    assert before <= pong["payload"]["ts"] <= after


def test_unknown_command_gets_an_error_reply_with_the_offending_id() -> None:
    with TestClient(create_app()) as client, client.websocket_connect("/ws") as ws:
        command_id = f"cmd-{uuid.uuid4()}"
        ws.send_text(_command("self.destruct", command_id))
        frame = receive_non_heartbeat_frame(ws)
    _assert_error_reply(frame, "unknown_command")
    assert frame["id"] == command_id  # correlatable rejection


def test_malformed_json_gets_an_error_and_the_socket_survives() -> None:
    """The critical fail-closed property: garbage → error reply, then the
    SAME connection still answers a ping. No crash, no disconnect."""
    with TestClient(create_app()) as client, client.websocket_connect("/ws") as ws:
        ws.send_text("{this is not json")
        error = receive_non_heartbeat_frame(ws)
        _assert_error_reply(error, "invalid_json")

        ping_id = str(uuid.uuid4())
        ws.send_text(_command("ping", ping_id))
        pong = receive_non_heartbeat_frame(ws)
        assert pong["name"] == "pong" and pong["id"] == ping_id


def test_invalid_envelope_over_the_wire_gets_a_structured_error() -> None:
    with TestClient(create_app()) as client, client.websocket_connect("/ws") as ws:
        bad_version = {"v": 2, "kind": "command", "name": "ping", "id": "x", "payload": {}}
        ws.send_text(json.dumps(bad_version))
        _assert_error_reply(receive_non_heartbeat_frame(ws), "invalid_envelope")


def test_client_sent_events_and_replies_are_rejected_not_dispatched() -> None:
    """Clients may only send commands; injected events/replies are refused."""
    with TestClient(create_app()) as client, client.websocket_connect("/ws") as ws:
        for kind in ("event", "reply"):
            spoof: dict[str, Any] = {
                "v": 1,
                "kind": kind,
                "name": "engine.heartbeat",
                "id": "spoof",
                "payload": {},
            }
            ws.send_text(json.dumps(spoof))
            frame = receive_non_heartbeat_frame(ws)
            _assert_error_reply(frame, "not_a_command")
            assert frame["id"] == "spoof"


def test_oversized_frame_is_rejected_and_the_socket_survives() -> None:
    with TestClient(create_app()) as client, client.websocket_connect("/ws") as ws:
        ws.send_text("x" * (64 * 1024 + 1))
        _assert_error_reply(receive_non_heartbeat_frame(ws), "message_too_large")
        ws.send_text(_command("ping", "still-alive"))
        assert receive_non_heartbeat_frame(ws)["id"] == "still-alive"


def test_a_barrage_of_hostile_frames_never_kills_the_connection() -> None:
    """Stateful abuse run: many bad frames in sequence, each answered, then
    normal service continues — the socket must be un-crashable from input."""
    hostile_frames = [
        "",
        "null",
        "[]",
        '"str"',
        "{}",
        '{"v":1}',
        json.dumps({"v": 1, "kind": "command", "name": "", "id": "e", "payload": {}}),
        json.dumps({"v": 1, "kind": "banana", "name": "n", "id": "e", "payload": {}}),
        json.dumps({"v": 1, "kind": "command", "name": "nope", "id": "e", "payload": {}, "x": 1}),
        "\x00\x01\x02",
    ]
    with TestClient(create_app()) as client, client.websocket_connect("/ws") as ws:
        for hostile in hostile_frames:
            ws.send_text(hostile)
            frame = receive_non_heartbeat_frame(ws)
            assert frame["name"] == "error", f"frame {hostile!r} did not yield an error"
        ws.send_text(_command("ping", "final-proof"))
        assert receive_non_heartbeat_frame(ws)["id"] == "final-proof"


def test_two_concurrent_connections_are_independent() -> None:
    """A hostile frame on one connection must not disturb another."""
    with (
        TestClient(create_app()) as client,
        client.websocket_connect("/ws") as ws_a,
        client.websocket_connect("/ws") as ws_b,
    ):
        ws_a.send_text("garbage")
        _assert_error_reply(receive_non_heartbeat_frame(ws_a), "invalid_json")
        ws_b.send_text(_command("ping", "b-ping"))
        pong_b = receive_non_heartbeat_frame(ws_b)
        assert pong_b["name"] == "pong" and pong_b["id"] == "b-ping"
