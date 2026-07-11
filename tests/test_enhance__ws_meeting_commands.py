"""WS meeting command surface: meeting.finalize / meetings.list / meeting.get.

Drives the REAL app + connection handler with an injected fake finalization
service: strict payload validation (deny by default), stable additive error
codes (finalize_error / not_found), reply-id correlation, event fan-out
during a finalize, and the honest refusal when no service is wired at all.
"""

import json
import uuid
from pathlib import Path
from typing import Any

from starlette.testclient import TestClient, WebSocketTestSession

from engine.enhance import (
    FinalizationResult,
    FinalizeRefusedError,
    MeetingFinalizationService,
)
from engine.enhance.meeting_command_dispatcher import dispatch_meeting_command
from engine.protocol import (
    Envelope,
    EnvelopeKind,
    EventBroadcastHub,
    build_enhance_ready_payload,
    build_enhance_started_payload,
)
from engine.server import create_app
from engine.storage.meetings_repository import MeetingRow
from engine.storage.transcript_segments_repository import TranscriptSegmentRow
from engine.stt.live_capture_service import LiveCaptureService
from tests.conftest import receive_frame

ROW = MeetingRow(
    id="m-1",
    title="Vendor sync",
    started_at="2026-07-06T10:00:00+00:00",
    ended_at="2026-07-06T10:30:00+00:00",
    note_path="Meetings/2026-07-06 Vendor sync.md",
    notes_text="raw",
    enhanced_notes_md="First line of the summary.",
    finalized_at="2026-07-06T10:31:00+00:00",
)
SEGMENTS = [
    TranscriptSegmentRow(
        segment_id="s1", stream="them", speaker_id="1", text="hello", t_start=0.0, t_end=1.0
    )
]


class FakeFinalizationService(MeetingFinalizationService):
    """Scripted service: no DB, no vault — just the reply/refusal semantics."""

    def __init__(self, hub: EventBroadcastHub) -> None:
        super().__init__(db_path=Path("unused.db"), migrations_dir=Path("unused"), hub=hub)
        self.finalize_calls: list[tuple[str, str, str | None]] = []
        self.delete_calls: list[str] = []

    async def list_meetings(self) -> list[MeetingRow]:
        return [ROW]

    async def get_meeting(
        self, meeting_id: str
    ) -> tuple[MeetingRow, list[TranscriptSegmentRow], str | None] | None:
        return (ROW, SEGMENTS, None) if meeting_id == ROW.id else None

    async def delete_meeting(self, meeting_id: str) -> dict[str, object] | None:
        self.delete_calls.append(meeting_id)
        if meeting_id != ROW.id:
            return None
        return {"deleted": True, "vault_note_kept": True}

    async def finalize(
        self, meeting_id: str, notepad_text: str, template_id: str | None
    ) -> FinalizationResult:
        self.finalize_calls.append((meeting_id, notepad_text, template_id))
        if meeting_id != ROW.id:
            raise FinalizeRefusedError(f"meeting {meeting_id!r} does not exist")
        # Real behaviour mirrored: progress events stream while the reply waits.
        await self._hub.broadcast_event(
            "enhance.started", build_enhance_started_payload(meeting_id)
        )
        await self._hub.broadcast_event(
            "enhance.ready", build_enhance_ready_payload(meeting_id, str(ROW.note_path))
        )
        return FinalizationResult(
            meeting_id=meeting_id,
            note_path=str(ROW.note_path),
            template_id="general",
            enhance_ok=True,
            extraction_ok=True,
            indexed_chunks=3,
        )


class InertCaptureService(LiveCaptureService):
    """Handler dependency only — capture is exercised in its own suite."""

    def __init__(self, hub: EventBroadcastHub) -> None:
        super().__init__(db_path=Path("unused.db"), migrations_dir=Path("unused"), hub=hub)


def make_app() -> tuple[Any, list[FakeFinalizationService]]:
    created: list[FakeFinalizationService] = []

    def finalization_factory(hub: EventBroadcastHub) -> MeetingFinalizationService:
        service = FakeFinalizationService(hub)
        created.append(service)
        return service

    app = create_app(
        capture_service_factory=InertCaptureService,
        finalization_service_factory=finalization_factory,
    )
    return app, created


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


# -------------------------------------------------------------- list / get
def test_meetings_list_replies_ok_with_the_pinned_summary_rows() -> None:
    app, _ = make_app()
    with TestClient(app) as client, client.websocket_connect("/ws") as ws:
        ws.send_text(command("meetings.list", {}, "list-1"))
        reply = collect_until_reply(ws)[-1]
    assert reply["name"] == "ok" and reply["id"] == "list-1"
    assert reply["payload"]["meetings"] == [
        {
            "id": "m-1",
            "title": "Vendor sync",
            "summary": "First line of the summary.",
            "start_iso": "2026-07-06T10:00:00+00:00",
            "duration_min": 30,
        }
    ]


def test_meetings_list_with_extra_fields_is_invalid_payload() -> None:
    app, _ = make_app()
    with TestClient(app) as client, client.websocket_connect("/ws") as ws:
        ws.send_text(command("meetings.list", {"page": 2}, "list-bad"))
        reply = collect_until_reply(ws)[-1]
    assert reply["name"] == "error"
    assert reply["payload"]["code"] == "invalid_payload"


def test_meeting_get_returns_detail_or_a_correlatable_not_found() -> None:
    app, _ = make_app()
    with TestClient(app) as client, client.websocket_connect("/ws") as ws:
        ws.send_text(command("meeting.get", {"meeting_id": "m-1"}, "get-1"))
        detail = collect_until_reply(ws)[-1]
        ws.send_text(command("meeting.get", {"meeting_id": "ghost"}, "get-2"))
        missing = collect_until_reply(ws)[-1]
    assert detail["name"] == "ok" and detail["id"] == "get-1"
    assert detail["payload"]["notes_text"] == "raw"
    assert detail["payload"]["transcript"] == [
        {
            "segment_id": "s1",
            "stream": "them",
            "speaker_id": "1",
            "speaker_label": "Speaker 1",
            "text": "hello",
            "t_start": 0.0,
            "t_end": 1.0,
        }
    ]
    assert missing["name"] == "error" and missing["id"] == "get-2"
    assert missing["payload"]["code"] == "not_found"


def test_meeting_get_without_an_id_is_invalid_payload() -> None:
    app, _ = make_app()
    with TestClient(app) as client, client.websocket_connect("/ws") as ws:
        ws.send_text(command("meeting.get", {}, "get-bad"))
        reply = collect_until_reply(ws)[-1]
    assert reply["payload"]["code"] == "invalid_payload"


# ---------------------------------------------------------------- finalize
def test_finalize_streams_progress_events_then_replies_ok() -> None:
    app, services = make_app()
    with TestClient(app) as client, client.websocket_connect("/ws") as ws:
        ws.send_text(
            command(
                "meeting.finalize",
                {"meeting_id": "m-1", "notepad_text": "my notes", "template": "general"},
                "fin-1",
            )
        )
        frames = collect_until_reply(ws)
    reply = frames[-1]
    assert reply["name"] == "ok" and reply["id"] == "fin-1"
    assert reply["payload"] == {
        "meeting_id": "m-1",
        "note_path": "Meetings/2026-07-06 Vendor sync.md",
        "template_id": "general",
        "enhance_ok": True,
        "extraction_ok": True,
        "indexed_chunks": 3,
        "warnings": [],
    }
    event_names = [f["name"] for f in frames if f["kind"] == "event"]
    assert event_names == ["enhance.started", "enhance.ready"]  # progress first
    assert services[0].finalize_calls == [("m-1", "my notes", "general")]


def test_finalize_refusal_maps_to_the_stable_finalize_error_code() -> None:
    app, _ = make_app()
    with TestClient(app) as client, client.websocket_connect("/ws") as ws:
        ws.send_text(
            command("meeting.finalize", {"meeting_id": "ghost", "notepad_text": ""}, "fin-2")
        )
        reply = collect_until_reply(ws)[-1]
    assert reply["name"] == "error" and reply["id"] == "fin-2"
    assert reply["payload"]["code"] == "finalize_error"
    assert "does not exist" in reply["payload"]["message"]


def test_finalize_hostile_payloads_are_denied_before_the_service_runs() -> None:
    app, services = make_app()
    hostile: list[dict[str, Any]] = [
        {},  # everything missing
        {"meeting_id": "m-1"},  # notepad_text missing
        {"meeting_id": "", "notepad_text": ""},  # empty id
        {"meeting_id": "m-1", "notepad_text": "x" * 20_001},  # over the bound
        {"meeting_id": "m-1", "notepad_text": "", "template": "t" * 65},  # template bound
        {"meeting_id": "m-1", "notepad_text": "", "run_now": True},  # unknown field
        {"meeting_id": 5, "notepad_text": ""},  # wrong type
    ]
    with TestClient(app) as client, client.websocket_connect("/ws") as ws:
        for payload in hostile:
            ws.send_text(command("meeting.finalize", payload, "bad"))
            reply = collect_until_reply(ws)[-1]
            assert reply["payload"]["code"] == "invalid_payload"
    assert services[0].finalize_calls == []  # nothing ever reached the service


def test_notepad_text_at_the_exact_bound_is_accepted() -> None:
    app, services = make_app()
    with TestClient(app) as client, client.websocket_connect("/ws") as ws:
        ws.send_text(
            command(
                "meeting.finalize",
                {"meeting_id": "m-1", "notepad_text": "x" * 20_000},
                "fin-3",
            )
        )
        reply = collect_until_reply(ws)[-1]
    assert reply["name"] == "ok"
    assert services[0].finalize_calls[0][1] == "x" * 20_000  # carried verbatim


def test_meeting_delete_replies_ok_and_not_found() -> None:
    app, services = make_app()
    with TestClient(app) as client, client.websocket_connect("/ws") as ws:
        ws.send_text(command("meeting.delete", {"meeting_id": "m-1"}, "del-1"))
        reply = collect_until_reply(ws)[-1]
    assert reply["name"] == "ok" and reply["id"] == "del-1"
    assert reply["payload"] == {"deleted": True, "vault_note_kept": True}
    assert services[0].delete_calls == ["m-1"]

    with TestClient(app) as client, client.websocket_connect("/ws") as ws:
        ws.send_text(command("meeting.delete", {"meeting_id": "missing"}, "del-2"))
        reply = collect_until_reply(ws)[-1]
    assert reply["name"] == "error" and reply["payload"]["code"] == "not_found"


# --------------------------------------------------------- unwired refusal
async def test_dispatch_without_a_service_refuses_honestly() -> None:
    sent: list[Envelope] = []

    async def send(envelope: Envelope) -> None:
        sent.append(envelope)

    envelope = Envelope(
        v=1, kind=EnvelopeKind.COMMAND, name="meetings.list", id="x-1", payload={}
    )
    await dispatch_meeting_command(envelope, None, send)
    assert len(sent) == 1
    assert sent[0].name == "error"
    assert sent[0].payload["code"] == "finalize_error"
    assert "not available" in str(sent[0].payload["message"])
