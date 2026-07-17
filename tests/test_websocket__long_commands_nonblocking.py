"""Long meeting commands run in background tasks so the receive loop drains.

While meeting.finalize (etc.) is in flight, a second command on the same
socket must still be processed and replied to.
"""

from __future__ import annotations

import asyncio
import contextlib
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

from engine.enhance.meeting_finalization_result_types import FinalizationResult
from engine.enhance.meeting_finalization_service import MeetingFinalizationService
from engine.protocol import Envelope, EventBroadcastHub
from engine.stt.live_capture_service import LiveCaptureService
from engine.websocket_connection_handler import WebSocketConnectionHandler


class _SlowFinalizationService(MeetingFinalizationService):
    def __init__(self, hub: EventBroadcastHub, gate: asyncio.Event) -> None:
        super().__init__(db_path=Path("unused.db"), migrations_dir=Path("unused"), hub=hub)
        self._gate = gate
        self.finalize_started = asyncio.Event()

    async def finalize(
        self, meeting_id: str, notepad_text: str, template_id: str | None
    ) -> FinalizationResult:
        self.finalize_started.set()
        await self._gate.wait()
        return FinalizationResult(
            meeting_id=meeting_id,
            note_path="Meetings/x.md",
            template_id="general",
            enhance_ok=True,
            extraction_ok=True,
            indexed_chunks=0,
        )


class _InertCapture(LiveCaptureService):
    def __init__(self, hub: EventBroadcastHub) -> None:
        super().__init__(db_path=Path("unused.db"), migrations_dir=Path("unused"), hub=hub)


def _cmd(name: str, payload: dict[str, Any], cmd_id: str) -> str:
    import json

    return json.dumps(
        {
            "v": 1,
            "kind": "command",
            "name": name,
            "id": cmd_id,
            "payload": payload,
        }
    )


async def test_second_command_processed_while_long_finalize_in_flight() -> None:
    hub = EventBroadcastHub()
    gate = asyncio.Event()
    service = _SlowFinalizationService(hub, gate)
    capture = _InertCapture(hub)
    replies: list[Envelope] = []

    ws = MagicMock()
    ws.send_text = AsyncMock()
    # receive_text sequence: finalize, then ping, then disconnect via CancelledError path
    frames = [
        _cmd("meeting.finalize", {"meeting_id": "m-1", "notepad_text": ""}, "fin-1"),
        _cmd("ping", {}, "ping-1"),
    ]
    frame_iter = iter(frames)

    async def receive_text() -> str:
        try:
            return next(frame_iter)
        except StopIteration:
            # Hold open until the test cancels the run task.
            await asyncio.Event().wait()
            raise AssertionError("unreachable") from None

    ws.receive_text = receive_text

    async def capturing_send(envelope: Envelope) -> None:
        replies.append(envelope)

    handler = WebSocketConnectionHandler(
        websocket=ws,
        started_monotonic=0.0,
        capture_service=capture,
        event_hub=hub,
        finalization_service=service,
    )
    # Bypass serialised send so we can observe replies without a real socket.
    handler._send = capturing_send  # type: ignore[method-assign]

    run_task = asyncio.create_task(handler.run())
    await service.finalize_started.wait()
    # Drain the event loop so the second frame (ping) is received and handled
    # while finalize is still blocked on the gate.
    for _ in range(50):
        await asyncio.sleep(0)
        if any(r.name == "pong" and r.id == "ping-1" for r in replies):
            break
    reply_names = [(r.name, r.id) for r in replies]
    assert any(r.name == "pong" and r.id == "ping-1" for r in replies), (
        f"ping not processed while finalize in flight; replies={reply_names}"
    )

    gate.set()
    for _ in range(50):
        await asyncio.sleep(0)
        if any(r.name == "ok" and r.id == "fin-1" for r in replies):
            break
    assert any(r.name == "ok" and r.id == "fin-1" for r in replies)

    run_task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await run_task
