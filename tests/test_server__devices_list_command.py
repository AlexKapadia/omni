"""WS device surface: ``devices.list`` -> typed real-device payload.

Drives the REAL app + connection handler with an injected fake lister:
exact payload shape (id/name/kind/is_default), strict command validation,
honest enumeration-failure and unwired refusals, and the kind allowlist on
the typed description itself (fail closed on a garbage kind).
"""

import json
import uuid
from pathlib import Path
from typing import Any

import pytest
from starlette.testclient import TestClient

from engine.audio.devices_list_command_dispatcher import dispatch_devices_command
from engine.protocol import AudioDeviceDescription, Envelope, EnvelopeKind, EventBroadcastHub
from engine.server import create_app
from engine.stt.live_capture_service import LiveCaptureService
from tests.conftest import receive_non_heartbeat_frame

DEVICES = [
    AudioDeviceDescription(
        id="3:Headset Microphone", name="Headset Microphone", kind="capture", is_default=True
    ),
    AudioDeviceDescription(
        id="7:Speakers [Loopback]", name="Speakers [Loopback]", kind="render", is_default=True
    ),
    AudioDeviceDescription(id="9:USB Mic", name="USB Mic", kind="capture", is_default=False),
]


class InertCaptureService(LiveCaptureService):
    def __init__(self, hub: EventBroadcastHub) -> None:
        super().__init__(db_path=Path("unused.db"), migrations_dir=Path("unused"), hub=hub)


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


def test_devices_list_replies_with_the_pinned_typed_rows() -> None:
    app = create_app(
        capture_service_factory=InertCaptureService, device_lister=lambda: list(DEVICES)
    )
    with TestClient(app) as client, client.websocket_connect("/ws") as ws:
        ws.send_text(command("devices.list", {}, "dev-1"))
        reply = receive_non_heartbeat_frame(ws)
    assert reply["name"] == "ok" and reply["id"] == "dev-1"
    assert reply["payload"] == {
        "devices": [
            {
                "id": "3:Headset Microphone",
                "name": "Headset Microphone",
                "kind": "capture",
                "is_default": True,
            },
            {
                "id": "7:Speakers [Loopback]",
                "name": "Speakers [Loopback]",
                "kind": "render",
                "is_default": True,
            },
            {"id": "9:USB Mic", "name": "USB Mic", "kind": "capture", "is_default": False},
        ]
    }


def test_devices_list_with_extra_fields_is_invalid_payload() -> None:
    app = create_app(
        capture_service_factory=InertCaptureService, device_lister=lambda: list(DEVICES)
    )
    with TestClient(app) as client, client.websocket_connect("/ws") as ws:
        ws.send_text(command("devices.list", {"refresh": True}, "dev-bad"))
        reply = receive_non_heartbeat_frame(ws)
    assert reply["name"] == "error"
    assert reply["payload"]["code"] == "invalid_payload"


def test_enumeration_failure_is_an_honest_devices_error_not_a_fake_list() -> None:
    def exploding_lister() -> list[AudioDeviceDescription]:
        raise OSError("PortAudio not initialised")

    app = create_app(
        capture_service_factory=InertCaptureService, device_lister=exploding_lister
    )
    with TestClient(app) as client, client.websocket_connect("/ws") as ws:
        ws.send_text(command("devices.list", {}, "dev-2"))
        reply = receive_non_heartbeat_frame(ws)
        assert reply["name"] == "error" and reply["id"] == "dev-2"
        assert reply["payload"]["code"] == "devices_error"
        assert "PortAudio" in reply["payload"]["message"]
        # The socket survives the failure.
        ws.send_text(command("ping", {}, "p-1"))
        assert receive_non_heartbeat_frame(ws)["name"] == "pong"


def test_device_description_rejects_garbage_kind_fail_closed() -> None:
    with pytest.raises(ValueError):
        AudioDeviceDescription(id="1:x", name="x", kind="loopback", is_default=False)


async def test_dispatch_without_a_lister_refuses_honestly() -> None:
    sent: list[Envelope] = []

    async def send(envelope: Envelope) -> None:
        sent.append(envelope)

    envelope = Envelope(v=1, kind=EnvelopeKind.COMMAND, name="devices.list", id="x-1", payload={})
    await dispatch_devices_command(envelope, None, send)
    assert len(sent) == 1 and sent[0].name == "error"
    assert sent[0].payload["code"] == "devices_error"
    assert "not available" in str(sent[0].payload["message"])
