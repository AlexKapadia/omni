"""M6 detection server wiring: decision -> event mapping, dismiss, VAD reset.

Pins the reconciliation wiring exactly: the pure ``decision_to_event``
mapping (payload shapes to the unit), the ``detection.dismiss`` round trip
into the rules engine's cooldown, strict dismiss validation, the honest
unwired refusal, decision broadcasts reaching connected sockets, and the
``capture.device_changed`` -> sustained-VAD-trigger reset.
"""

import asyncio
import json
import uuid
from pathlib import Path
from typing import Any

import pytest
from starlette.testclient import TestClient

from engine.detect import (
    AutoStart,
    AutoStartRulesEngine,
    DesktopSnapshot,
    DetectionService,
    MeetingProcessWatcher,
    MicrophoneInUseDetector,
    SuggestCapture,
    SuggestStop,
    SustainedLoopbackVadTrigger,
)
from engine.detect.detection_dismiss_command_dispatcher import dispatch_detection_command
from engine.detection_server_wiring import DetectionServerWiring, decision_to_event
from engine.protocol import (
    EVENT_CAPTURE_DEVICE_CHANGED,
    Envelope,
    EnvelopeKind,
    EventBroadcastHub,
    build_capture_device_changed_payload,
)
from engine.server import create_app
from engine.stt.live_capture_service import LiveCaptureService
from tests.conftest import receive_non_heartbeat_frame

# ------------------------------------------------------ decision mapping


def test_suggest_capture_maps_to_meeting_detected_with_dedupe_key() -> None:
    name, payload = decision_to_event(
        SuggestCapture(reason="zoom meeting activity detected", source="zoom", confidence=0.7,
                       dedupe_key="zoom")
    )
    assert name == "meeting.detected"
    assert payload == {
        "source": "zoom",
        "reason": "zoom meeting activity detected",
        "confidence": 0.7,
        "dedupe_key": "zoom",
    }  # no auto_start key at all: a suggestion card, nothing more


def test_auto_start_maps_to_meeting_detected_with_auto_start_true() -> None:
    name, payload = decision_to_event(
        AutoStart(reason="teams meeting detected (user-enabled auto-start)", source="teams",
                  confidence=0.9)
    )
    assert name == "meeting.detected"
    assert payload == {
        "source": "teams",
        "reason": "teams meeting detected (user-enabled auto-start)",
        "confidence": 0.9,
        "auto_start": True,
    }


def test_suggest_stop_maps_to_capture_suggest_stop() -> None:
    name, payload = decision_to_event(
        SuggestStop(reason="meeting app closed while capture is still running")
    )
    assert name == "capture.suggest_stop"
    assert payload == {"reason": "meeting app closed while capture is still running"}


def test_unknown_decision_type_fails_loudly_never_a_guessed_shape() -> None:
    with pytest.raises(TypeError):
        decision_to_event("not a decision")  # type: ignore[arg-type]


# ------------------------------------------------- wiring over a fake service


def make_detection_service(
    on_decision: Any, vad_trigger: SustainedLoopbackVadTrigger
) -> DetectionService:
    """A real DetectionService over inert fakes (no OS probes, no polling)."""
    return DetectionService(
        process_watcher=MeetingProcessWatcher(lambda: DesktopSnapshot((), ())),
        microphone_detector=MicrophoneInUseDetector(lambda: ()),
        vad_trigger=vad_trigger,
        rules_engine=AutoStartRulesEngine(),
        is_capture_active=lambda: False,
        on_decision=on_decision,
    )


async def test_decision_callback_broadcasts_the_mapped_event_on_the_hub() -> None:
    hub = EventBroadcastHub()
    received: list[Envelope] = []

    async def subscriber(envelope: Envelope) -> None:
        received.append(envelope)

    hub.subscribe(subscriber)
    trigger = SustainedLoopbackVadTrigger()
    wiring = DetectionServerWiring(
        hub,
        is_capture_active=lambda: False,
        service=make_detection_service(lambda d: None, trigger),
        vad_trigger=trigger,
    )
    # Drive the wiring's own callback exactly as DetectionService would.
    wiring._on_decision(SuggestCapture(reason="r", source="zoom", confidence=0.8,
                                       dedupe_key="zoom"))
    await asyncio.sleep(0)  # let the scheduled broadcast task run
    assert [e.name for e in received] == ["meeting.detected"]
    assert received[0].payload["dedupe_key"] == "zoom"


async def test_device_changed_event_resets_the_sustained_vad_trigger() -> None:
    hub = EventBroadcastHub()
    trigger = SustainedLoopbackVadTrigger()
    wiring = DetectionServerWiring(
        hub,
        is_capture_active=lambda: False,
        service=make_detection_service(lambda d: None, trigger),
        vad_trigger=trigger,
    )
    assert wiring is not None
    # Accumulate real speech-time state in the trigger...
    trigger.feed(0.0, 0.9, capture_active=False)
    trigger.feed(0.5, 0.9, capture_active=False)
    assert trigger.speech_seconds_in_window > 0.0
    # ...then a device change must drop ALL rolling accounting (boundary:
    # stale speech from the old endpoint must not bill the new one).
    await hub.broadcast_event(
        EVENT_CAPTURE_DEVICE_CHANGED, build_capture_device_changed_payload("Headset", 42.0)
    )
    assert trigger.speech_seconds_in_window == 0.0


# --------------------------------------------------------- dismiss round trip


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


def make_app_with_detection() -> tuple[Any, AutoStartRulesEngine]:
    """Real app + real rules engine behind a non-polling detection service."""
    rules = AutoStartRulesEngine()
    trigger = SustainedLoopbackVadTrigger()

    def factory(hub: EventBroadcastHub, capture: LiveCaptureService) -> DetectionServerWiring:
        service = DetectionService(
            process_watcher=MeetingProcessWatcher(lambda: DesktopSnapshot((), ())),
            microphone_detector=MicrophoneInUseDetector(lambda: ()),
            vad_trigger=trigger,
            rules_engine=rules,
            is_capture_active=lambda: capture.is_capturing,
            on_decision=lambda decision: None,
            # Poll interval is irrelevant: the test never lets a tick fire
            # decisions (empty snapshots yield no signals anyway).
        )
        return DetectionServerWiring(
            hub, is_capture_active=lambda: capture.is_capturing, service=service,
            vad_trigger=trigger,
        )

    app = create_app(
        capture_service_factory=InertCaptureService, detection_wiring_factory=factory
    )
    return app, rules


def test_detection_dismiss_round_trip_suppresses_the_dedupe_key() -> None:
    app, rules = make_app_with_detection()
    with TestClient(app) as client, client.websocket_connect("/ws") as ws:
        ws.send_text(command("detection.dismiss", {"dedupe_key": "zoom"}, "d-1"))
        reply = receive_non_heartbeat_frame(ws)
    assert reply["name"] == "ok" and reply["id"] == "d-1" and reply["payload"] == {}
    # The engine recorded the cooldown: an immediate zoom session may not
    # suggest again (deny within the cooldown window — rules-engine contract).
    decisions = rules.update(
        now_s=1.0,
        signals=[],
        capture_active=False,
    )
    assert decisions == []
    assert rules._dismissed_until_s["zoom"] > 0.0  # cooldown actually armed


def test_detection_dismiss_hostile_payloads_are_invalid_payload() -> None:
    app, _ = make_app_with_detection()
    hostile: list[dict[str, Any]] = [
        {},  # key missing
        {"dedupe_key": ""},  # empty
        {"dedupe_key": "x" * 129},  # just over the bound
        {"dedupe_key": "zoom", "force": True},  # unknown field
        {"dedupe_key": 3},  # wrong type
    ]
    with TestClient(app) as client, client.websocket_connect("/ws") as ws:
        for payload in hostile:
            ws.send_text(command("detection.dismiss", payload, "d-bad"))
            reply = receive_non_heartbeat_frame(ws)
            assert reply["name"] == "error"
            assert reply["payload"]["code"] == "invalid_payload"


def test_dismiss_without_detection_wired_refuses_honestly() -> None:
    app = create_app(capture_service_factory=InertCaptureService)  # detection unwired
    with TestClient(app) as client, client.websocket_connect("/ws") as ws:
        ws.send_text(command("detection.dismiss", {"dedupe_key": "zoom"}, "d-2"))
        reply = receive_non_heartbeat_frame(ws)
    assert reply["name"] == "error" and reply["id"] == "d-2"
    assert reply["payload"]["code"] == "detection_error"
    assert "not available" in reply["payload"]["message"]


async def test_dispatch_without_a_service_refuses_honestly() -> None:
    sent: list[Envelope] = []

    async def send(envelope: Envelope) -> None:
        sent.append(envelope)

    envelope = Envelope(
        v=1,
        kind=EnvelopeKind.COMMAND,
        name="detection.dismiss",
        id="x-1",
        payload={"dedupe_key": "zoom"},
    )
    await dispatch_detection_command(envelope, None, send)
    assert len(sent) == 1 and sent[0].name == "error"
    assert sent[0].payload["code"] == "detection_error"
