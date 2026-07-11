"""WS dictation surface: ``dictation.begin`` / ``dictation.end`` wiring.

Drives the REAL app + connection handler with a fake session service and a
fake release-finalize seam, pinning the deferred spec in
``engine/dictation/dictation_protocol_names.py``: begin/end replies, the
``dictation.final`` broadcast built from the finalizer result, the
``flush_ms`` hand-off, the DENY-BY-DEFAULT ``inject_requested`` coercion
(only the literal True routes toward a paste), and the ``dictation.error``
event + error reply on failure.
"""

import json
import uuid
from pathlib import Path
from typing import Any

from starlette.testclient import TestClient, WebSocketTestSession

from engine.dictation.dictation_finalization import DictationFinalResult
from engine.dictation.dictation_mode_splitter import DictationMode
from engine.dictation.dictation_session_service import (
    DictationSessionError,
    DictationSessionService,
)
from engine.protocol import Envelope, EnvelopeKind, EventBroadcastHub
from engine.server import create_app
from engine.stt.live_capture_service import LiveCaptureService
from engine.wiring.dictation_command_dispatcher import (
    DictationCommandGateway,
    dispatch_dictation_command,
)
from tests.conftest import receive_frame


class FakeSessionService(DictationSessionService):
    """Scripted mic session: no audio, no models — lifecycle semantics only."""

    def __init__(self) -> None:
        super().__init__()
        self.begin_calls = 0
        self.end_calls = 0
        self.cancel_calls = 0
        self.begin_raises: Exception | None = None
        self.transcript = "buy milk tomorrow"
        self.last_flush_ms = 87

    async def begin(self) -> None:
        self.begin_calls += 1
        if self.begin_raises is not None:
            raise self.begin_raises

    async def end(self) -> str:
        self.end_calls += 1
        return self.transcript

    async def cancel(self) -> None:
        self.cancel_calls += 1


class RecordingReleaseFinalize:
    """Fake release-finalize seam: records args, returns a NOTE result."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, bool, int | None]] = []

    async def __call__(
        self, text: str, inject_requested: bool, flush_ms: int | None
    ) -> DictationFinalResult:
        self.calls.append((text, inject_requested, flush_ms))
        return DictationFinalResult(
            mode=DictationMode.NOTE,
            text=text,
            note_path="C:/vault/Inbox/buy milk.md",
            note_title="buy milk",
            title_source="model",
            cleaned_text="Buy milk tomorrow.",
            cleanup_source="model",
            cleanup_latency_ms=210,
            flush_ms=flush_ms,
        )


class InertCaptureService(LiveCaptureService):
    """Handler dependency only — capture is exercised in its own suite."""

    def __init__(self, hub: EventBroadcastHub) -> None:
        super().__init__(db_path=Path("unused.db"), migrations_dir=Path("unused"), hub=hub)


def make_app() -> tuple[Any, FakeSessionService, RecordingReleaseFinalize]:
    session = FakeSessionService()
    finalize = RecordingReleaseFinalize()

    def gateway_factory(hub: EventBroadcastHub) -> DictationCommandGateway:
        return DictationCommandGateway(
            hub=hub,
            db_path=Path("unused.db"),
            migrations_dir=Path("unused"),
            session_service=session,
            release_finalize=finalize,
        )

    app = create_app(
        capture_service_factory=InertCaptureService, dictation_gateway_factory=gateway_factory
    )
    return app, session, finalize


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
    frames: list[dict[str, Any]] = []
    for _ in range(limit):
        frame = receive_frame(ws)
        if frame.get("name") == "engine.heartbeat":
            continue
        frames.append(frame)
        if frame["kind"] == "reply":
            return frames
    raise AssertionError(f"no reply within {limit} frames: {frames}")


def test_begin_replies_ok_and_ignores_the_advisory_mode_hint() -> None:
    app, session, _ = make_app()
    with TestClient(app) as client, client.websocket_connect("/ws") as ws:
        ws.send_text(command("dictation.begin", {"mode_hint": "command"}, "b-1"))
        reply = collect_until_reply(ws)[-1]
    assert reply["name"] == "ok" and reply["id"] == "b-1" and reply["payload"] == {}
    assert session.begin_calls == 1  # hint advisory only; the engine ignores it


def test_end_runs_the_finalizer_and_broadcasts_dictation_final_before_ok() -> None:
    app, session, finalize = make_app()
    with TestClient(app) as client, client.websocket_connect("/ws") as ws:
        ws.send_text(command("dictation.end", {}, "e-1"))
        frames = collect_until_reply(ws)
    reply = frames[-1]
    assert reply["name"] == "ok" and reply["id"] == "e-1" and reply["payload"] == {}
    assert session.end_calls == 1
    # flush_ms flows from the session's wiring-measured stamp (spec).
    assert finalize.calls == [("buy milk tomorrow", False, 87)]
    events = [f for f in frames if f["kind"] == "event" and f["name"] == "dictation.final"]
    assert len(events) == 1  # the broadcast precedes the acknowledging reply
    payload = events[0]["payload"]
    assert payload["mode"] == "note"
    assert payload["text"] == "buy milk tomorrow"  # RAW verbatim (fidelity)
    assert payload["cleaned_text"] == "Buy milk tomorrow."
    assert payload["note_title"] == "buy milk"
    assert payload["flush_ms"] == 87


def test_inject_requested_is_deny_by_default_only_the_literal_true_passes() -> None:
    app, _, finalize = make_app()
    # (wire value, expected inject flag): anything but literal True is False.
    cases: list[tuple[Any, bool]] = [
        (True, True),
        (False, False),
        ("true", False),
        ("yes", False),
        (1, False),
        (0, False),
        (None, False),
        ([True], False),
    ]
    with TestClient(app) as client, client.websocket_connect("/ws") as ws:
        for wire_value, expected in cases:
            ws.send_text(command("dictation.end", {"inject_requested": wire_value}))
            assert collect_until_reply(ws)[-1]["name"] == "ok"
            assert finalize.calls[-1][1] is expected, f"wire value {wire_value!r}"


def test_begin_failure_emits_dictation_error_event_and_error_reply() -> None:
    app, session, _ = make_app()
    session.begin_raises = DictationSessionError("VAD model missing: silero.onnx")
    with TestClient(app) as client, client.websocket_connect("/ws") as ws:
        ws.send_text(command("dictation.begin", {}, "b-2"))
        frames = collect_until_reply(ws)
        reply = frames[-1]
        assert reply["name"] == "error" and reply["id"] == "b-2"
        assert reply["payload"]["code"] == "dictation_error"
        assert "VAD model missing" in reply["payload"]["message"]
        error_events = [
            f for f in frames if f["kind"] == "event" and f["name"] == "dictation.error"
        ]
        assert len(error_events) == 1
        assert "VAD model missing" in error_events[0]["payload"]["reason"]
        # The socket survives the failure (fail closed, stay up).
        session.begin_raises = None
        ws.send_text(command("dictation.begin", {}, "b-3"))
        assert collect_until_reply(ws)[-1]["name"] == "ok"


async def test_dispatch_without_a_gateway_refuses_honestly() -> None:
    sent: list[Envelope] = []

    async def send(envelope: Envelope) -> None:
        sent.append(envelope)

    envelope = Envelope(
        v=1, kind=EnvelopeKind.COMMAND, name="dictation.begin", id="x-1", payload={}
    )
    await dispatch_dictation_command(envelope, None, send)
    assert len(sent) == 1
    assert sent[0].name == "error"
    assert sent[0].payload["code"] == "dictation_error"
    assert "not available" in str(sent[0].payload["message"])


def test_cancel_tears_down_without_finalizing_or_broadcasting_final() -> None:
    """Cancel must abort the mic session without writing a note / history."""
    app, session, finalize = make_app()
    with TestClient(app) as client, client.websocket_connect("/ws") as ws:
        ws.send_text(command("dictation.begin", {}, "b-c"))
        assert collect_until_reply(ws)[-1]["name"] == "ok"
        ws.send_text(command("dictation.cancel", {}, "c-1"))
        frames = collect_until_reply(ws)
    reply = frames[-1]
    assert reply["name"] == "ok" and reply["id"] == "c-1"
    assert session.cancel_calls == 1
    assert session.end_calls == 0
    assert finalize.calls == []
    finals = [f for f in frames if f["kind"] == "event" and f["name"] == "dictation.final"]
    assert finals == []
