"""Integration tests: markdown export + text replace on a real DB."""

import json
import uuid
from pathlib import Path
from typing import Any

import pytest
from starlette.testclient import TestClient

from engine.enhance.meeting_finalization_service import MeetingFinalizationService
from engine.protocol import EventBroadcastHub
from engine.server import create_app
from engine.storage.meetings_repository import record_meeting_finalization, utc_now_iso
from engine.storage.sqlite_connection import open_sqlite_connection
from engine.stt.live_capture_service import LiveCaptureService
from tests.conftest import receive_frame
from tests.enhance_test_support import seed_meeting


class InertCaptureService(LiveCaptureService):
    def __init__(self, hub: EventBroadcastHub, db_path: Path, migrations_dir: Path) -> None:
        super().__init__(db_path=db_path, migrations_dir=migrations_dir, hub=hub)


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


def _reply(ws: Any, limit: int = 20) -> dict[str, Any]:
    for _ in range(limit):
        frame = receive_frame(ws)
        if frame.get("name") == "engine.heartbeat":
            continue
        if frame["kind"] == "reply":
            return frame
    raise AssertionError("no reply")


@pytest.mark.asyncio
async def test_export_md_returns_full_meeting_markdown(
    tmp_db_path: Path, real_migrations_dir: Path
) -> None:
    await seed_meeting(
        tmp_db_path,
        real_migrations_dir,
        "m-md",
        title="Budget sync",
        segments=(("them", "Deadline Friday"), ("me", "Will deliver")),
    )
    connection = await open_sqlite_connection(tmp_db_path)
    try:
        await record_meeting_finalization(
            connection,
            "m-md",
            note_path="Meetings/budget.md",
            notes_text="rough",
            enhanced_notes_md="## Summary\nApproved.",
            finalized_at_iso=utc_now_iso(),
        )
        await connection.commit()
    finally:
        await connection.close()

    EventBroadcastHub()

    def finalization_factory(h: EventBroadcastHub) -> MeetingFinalizationService:
        return MeetingFinalizationService(
            db_path=tmp_db_path, migrations_dir=real_migrations_dir, hub=h
        )

    app = create_app(
        capture_service_factory=lambda h: InertCaptureService(
            h, tmp_db_path, real_migrations_dir
        ),
        finalization_service_factory=finalization_factory,
    )
    with TestClient(app) as client, client.websocket_connect("/ws") as ws:
        ws.send_text(
            _command("meeting.export", {"meeting_id": "m-md", "format": "md"}, "exp-md")
        )
        reply = _reply(ws)
    assert reply["name"] == "ok"
    content = reply["payload"]["content"]
    assert isinstance(content, str)
    assert "# Budget sync" in content
    assert "## Enhanced Notes" in content
    assert "## Transcript" in content
    assert "Deadline Friday" in content


@pytest.mark.asyncio
async def test_text_replace_via_ws_updates_segments(
    tmp_db_path: Path, real_migrations_dir: Path
) -> None:
    await seed_meeting(
        tmp_db_path,
        real_migrations_dir,
        "m-rep",
        segments=(("them", "call Acme Corp"),),
    )
    connection = await open_sqlite_connection(tmp_db_path)
    try:
        await record_meeting_finalization(
            connection,
            "m-rep",
            note_path="Meetings/x.md",
            notes_text="",
            enhanced_notes_md="Mentioned Acme Corp in summary.",
            finalized_at_iso=utc_now_iso(),
        )
        await connection.commit()
    finally:
        await connection.close()

    hub = EventBroadcastHub()

    def finalization_factory(h: EventBroadcastHub) -> MeetingFinalizationService:
        return MeetingFinalizationService(
            db_path=tmp_db_path, migrations_dir=real_migrations_dir, hub=h
        )

    app = create_app(
        capture_service_factory=lambda h: InertCaptureService(
            h, tmp_db_path, real_migrations_dir
        ),
        finalization_service_factory=finalization_factory,
    )
    with TestClient(app) as client, client.websocket_connect("/ws") as ws:
        ws.send_text(
            _command(
                "meeting.text.replace",
                {
                    "meeting_id": "m-rep",
                    "find": "Acme Corp",
                    "replace": "ACME",
                    "target": "both",
                },
                "rep-1",
            )
        )
        reply = _reply(ws)
    assert reply["name"] == "ok"
    assert reply["payload"]["transcript_segments"] == 1
    assert reply["payload"]["enhanced_notes"] == 1

    service = MeetingFinalizationService(
        db_path=tmp_db_path, migrations_dir=real_migrations_dir, hub=hub
    )
    loaded = await service.get_meeting("m-rep")
    assert loaded is not None
    row, segments, _ = loaded
    assert "ACME" in segments[0].text
    assert row.enhanced_notes_md is not None
    assert "ACME" in row.enhanced_notes_md
