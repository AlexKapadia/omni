"""naomi.say / naomi.cancel over the REAL WS surface (protocol v1).

Drives the real app + connection handler (fake capture service, zero
network): payload validation must be strict, refusals (kill switch,
missing credentials) must be structured voice_error replies that never
crash the socket, and cancel must be idempotent. The one-real-call TTFA
measurement lives in engine/voice/naomi_ttfa_live_probe.py — deliberately
OUTSIDE this hermetic suite.
"""

import json
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from starlette.testclient import TestClient, WebSocketTestSession

from engine.protocol import EventBroadcastHub
from engine.security.kill_switch import (
    KILL_SWITCH_ENV_VAR,
    set_kill_switch_runtime_override,
)
from engine.server import create_app
from engine.stt.live_capture_service import LiveCaptureService
from tests.conftest import receive_frame


@pytest.fixture(autouse=True)
def _clean_voice_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Hermetic: no kill switch, no Cartesia credentials, no network."""
    monkeypatch.delenv(KILL_SWITCH_ENV_VAR, raising=False)
    monkeypatch.delenv("CARTESIA_API_KEY", raising=False)
    monkeypatch.delenv("CARTESIA_VOICE_ID", raising=False)
    set_kill_switch_runtime_override(None)
    yield
    set_kill_switch_runtime_override(None)


class IdleCaptureService(LiveCaptureService):
    """No-hardware stand-in so create_app boots without audio/models."""

    def __init__(self, hub: EventBroadcastHub) -> None:
        super().__init__(db_path=Path("unused.db"), migrations_dir=Path("unused"), hub=hub)


def make_app() -> Any:
    return create_app(capture_service_factory=IdleCaptureService)


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


def reply_for(ws: WebSocketTestSession, limit: int = 20) -> dict[str, Any]:
    for _ in range(limit):
        frame = receive_frame(ws)
        if frame["kind"] == "reply":
            return frame
    raise AssertionError("no reply received")


def test_say_without_credentials_is_an_honest_voice_error_not_a_crash() -> None:
    app = make_app()
    with TestClient(app) as client, client.websocket_connect("/ws") as ws:
        ws.send_text(command("naomi.say", {"text": "Hello Naomi"}, "say-1"))
        reply = reply_for(ws)
        assert reply["name"] == "error"
        assert reply["id"] == "say-1"  # correlation contract
        assert reply["payload"]["code"] == "voice_error"
        assert "CARTESIA_API_KEY" in reply["payload"]["message"]  # names the var
        # The socket survived: ping still answers.
        ws.send_text(command("ping", {}, "ping-after"))
        assert reply_for(ws)["name"] == "pong"


def test_say_with_kill_switch_engaged_refuses_before_any_egress(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(KILL_SWITCH_ENV_VAR, "1")
    # Credentials present — proving the refusal is the SWITCH, not the keys.
    monkeypatch.setenv("CARTESIA_API_KEY", "sk-car-test-0123456789")
    monkeypatch.setenv("CARTESIA_VOICE_ID", "voice-x")
    app = make_app()
    with TestClient(app) as client, client.websocket_connect("/ws") as ws:
        ws.send_text(command("naomi.say", {"text": "Hello"}, "say-ks"))
        reply = reply_for(ws)
        assert reply["payload"]["code"] == "voice_error"
        assert "kill switch" in reply["payload"]["message"].lower()


def test_malformed_say_payloads_get_invalid_payload() -> None:
    app = make_app()
    hostile: list[dict[str, Any]] = [
        {},  # missing text
        {"text": ""},  # empty text
        {"text": "x" * 2001},  # over the bound
        {"text": 42},  # wrong type
        {"text": "ok", "extra": "field"},  # unknown field: deny by default
        {"text": "ok", "affect": {"v": 2, "a": 0.5}},  # valence out of range
        {"text": "ok", "affect": {"v": 0.5, "a": -0.1}},  # arousal out of range
        {"text": "ok", "affect": {"v": 0.5, "a": 0.5, "burst": "sob"}},  # unknown burst
        {"text": "ok", "affect": {"v": 0.5, "a": 0.5, "rogue": 1}},  # extra in affect
    ]
    with TestClient(app) as client, client.websocket_connect("/ws") as ws:
        for payload in hostile:
            ws.send_text(command("naomi.say", payload, "bad-say"))
            reply = reply_for(ws)
            assert reply["name"] == "error"
            assert reply["payload"]["code"] == "invalid_payload"


def test_cancel_with_nothing_speaking_replies_ok_null() -> None:
    app = make_app()
    with TestClient(app) as client, client.websocket_connect("/ws") as ws:
        ws.send_text(command("naomi.cancel", {}, "cancel-1"))
        reply = reply_for(ws)
        assert reply["name"] == "ok"
        assert reply["id"] == "cancel-1"
        assert reply["payload"] == {"cancelled_context_id": None}


def test_cancel_rejects_extra_fields() -> None:
    app = make_app()
    with TestClient(app) as client, client.websocket_connect("/ws") as ws:
        ws.send_text(command("naomi.cancel", {"force": True}, "cancel-bad"))
        reply = reply_for(ws)
        assert reply["payload"]["code"] == "invalid_payload"


def test_boundary_say_text_lengths_validate_exactly() -> None:
    """2000 chars is legal, 2001 is not — the bound is exact (but with no
    credentials the 2000 case surfaces as voice_error AFTER validation)."""
    app = make_app()
    with TestClient(app) as client, client.websocket_connect("/ws") as ws:
        ws.send_text(command("naomi.say", {"text": "x" * 2000}, "say-max"))
        reply = reply_for(ws)
        assert reply["payload"]["code"] == "voice_error"  # passed validation
        ws.send_text(command("naomi.say", {"text": "x" * 2001}, "say-over"))
        reply = reply_for(ws)
        assert reply["payload"]["code"] == "invalid_payload"  # failed validation
