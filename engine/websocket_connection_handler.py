"""Per-connection WebSocket logic: heartbeat emission and command dispatch.

Purpose: owns the lifetime of one UI<->engine WebSocket — starts the
heartbeat task, receives frames, dispatches commands, and guarantees the
socket never crashes on bad input.
Pipeline position: called by ``engine.server``'s /ws endpoint; speaks only
``engine.protocol`` shapes.

Security invariants:
- Every inbound frame goes through ``parse_envelope`` (untrusted input,
  size-capped, strictly validated) before any dispatch — deny by default.
- Unknown or malformed frames get a structured `error` reply; exceptions
  from parsing never propagate (fail closed, connection stays healthy).
- Only ``kind == "command"`` frames are dispatched; clients cannot inject
  events or replies into the engine.
"""

import asyncio
import contextlib
import time
import uuid

from fastapi import WebSocket, WebSocketDisconnect

from engine.approval_cards_gateway import ApprovalCardsGateway
from engine.approval_command_dispatcher import (
    APPROVAL_COMMAND_NAMES,
    dispatch_approval_command,
)
from engine.ask.ask_query_command_dispatcher import (
    ASK_COMMAND_NAMES,
    AskAnswerGateway,
    dispatch_ask_command,
)
from engine.audio.devices_list_command_dispatcher import (
    DEVICES_COMMAND_NAMES,
    DeviceLister,
    dispatch_devices_command,
)
from engine.capture_command_dispatcher import CAPTURE_COMMAND_NAMES, dispatch_capture_command
from engine.detect.detection_dismiss_command_dispatcher import (
    DETECTION_COMMAND_NAMES,
    dispatch_detection_command,
)
from engine.detect.detection_service import DetectionService
from engine.dictation_command_dispatcher import (
    DICTATION_COMMAND_NAMES,
    DictationCommandGateway,
    dispatch_dictation_command,
)
from engine.enhance import (
    MEETING_COMMAND_NAMES,
    MeetingFinalizationService,
    dispatch_meeting_command,
)
from engine.protocol import (
    PROTOCOL_VERSION,
    Envelope,
    EnvelopeKind,
    EventBroadcastHub,
    ProtocolError,
    ProtocolErrorCode,
    build_heartbeat_payload,
    error_reply,
    parse_envelope,
)
from engine.runtime_settings import HEARTBEAT_INTERVAL_SECONDS
from engine.stt.live_capture_service import LiveCaptureService
from engine.voice import NAOMI_COMMAND_NAMES, TtsPlaybackStreamer, dispatch_naomi_command


class WebSocketConnectionHandler:
    """Runs one accepted WebSocket connection to completion."""

    def __init__(
        self,
        websocket: WebSocket,
        started_monotonic: float,
        capture_service: LiveCaptureService,
        event_hub: EventBroadcastHub,
        voice_streamer: TtsPlaybackStreamer | None = None,
        finalization_service: MeetingFinalizationService | None = None,
        ask_gateway: AskAnswerGateway | None = None,
        dictation_gateway: DictationCommandGateway | None = None,
        approval_gateway: ApprovalCardsGateway | None = None,
        detection_service: DetectionService | None = None,
        device_lister: DeviceLister | None = None,
    ) -> None:
        self._websocket = websocket
        self._started_monotonic = started_monotonic
        self._capture_service = capture_service
        self._event_hub = event_hub
        # Optional additive surface: None → naomi.* commands refuse honestly.
        self._voice_streamer = voice_streamer
        # Optional additive surface: None → meeting.* commands refuse honestly.
        self._finalization_service = finalization_service
        # Optional additive surfaces (reconciliation pass): each dispatcher
        # refuses honestly when its dependency is None — deny by default.
        self._ask_gateway = ask_gateway
        self._dictation_gateway = dictation_gateway
        self._approval_gateway = approval_gateway
        self._detection_service = detection_service
        self._device_lister = device_lister
        # Multiple tasks write to one socket (heartbeat + replies + broadcast
        # events); the lock serialises sends so frames never interleave.
        self._send_lock = asyncio.Lock()

    async def run(self) -> None:
        """Serve the connection until the client disconnects.

        The heartbeat runs as a sibling task and is always cancelled and
        awaited on exit so no orphan task outlives the socket. The hub
        subscription is likewise always released (no broadcasts to a dead
        socket).
        """
        heartbeat_task = asyncio.create_task(self._emit_heartbeats())
        unsubscribe = self._event_hub.subscribe(self._send)
        try:
            while True:
                raw = await self._websocket.receive_text()
                await self._handle_frame(raw)
        except WebSocketDisconnect:
            pass  # Normal client hang-up; nothing to report.
        finally:
            unsubscribe()
            heartbeat_task.cancel()
            # Await cancellation so shutdown is graceful, not fire-and-forget.
            with contextlib.suppress(asyncio.CancelledError):
                await heartbeat_task

    async def _send(self, envelope: Envelope) -> None:
        """Serialised send — the only path that writes to the socket."""
        async with self._send_lock:
            await self._websocket.send_text(envelope.to_wire())

    async def _emit_heartbeats(self) -> None:
        """Emit `engine.heartbeat` immediately, then every ~2 s.

        Immediate first beat: the UI learns engine liveness/version at
        connect time instead of waiting a full interval.
        """
        while True:
            heartbeat = Envelope(
                v=PROTOCOL_VERSION,
                kind=EnvelopeKind.EVENT,
                name="engine.heartbeat",
                id=str(uuid.uuid4()),
                payload=build_heartbeat_payload(
                    self._started_monotonic,
                    # Live truth per beat: flips true once models are loaded.
                    stt_ready=self._capture_service.is_stt_ready,
                ),
            )
            await self._send(heartbeat)
            await asyncio.sleep(HEARTBEAT_INTERVAL_SECONDS)

    async def _handle_frame(self, raw: str) -> None:
        """Validate one untrusted frame and dispatch or reject it.

        Fail closed: every rejection path answers with an `error` reply and
        returns normally — a hostile frame must never kill the socket.
        """
        try:
            envelope = parse_envelope(raw)
        except ProtocolError as exc:
            # The frame's id may be unextractable (malformed JSON); a fresh
            # id keeps the reply well-formed either way.
            reply_id = _best_effort_frame_id(raw)
            await self._send(error_reply(reply_id, exc.code, exc.message))
            return

        if envelope.kind is not EnvelopeKind.COMMAND:
            # Clients may only send commands; events/replies are rejected.
            await self._send(
                error_reply(
                    envelope.id,
                    ProtocolErrorCode.NOT_A_COMMAND,
                    f"clients may only send commands, got kind={envelope.kind.value!r}",
                )
            )
            return

        await self._dispatch_command(envelope)

    async def _dispatch_command(self, command: Envelope) -> None:
        """Route a validated command to its handler; unknown → error reply."""
        if command.name == "ping":
            await self._send(
                Envelope(
                    v=PROTOCOL_VERSION,
                    kind=EnvelopeKind.REPLY,
                    name="pong",
                    id=command.id,  # Contract: pong carries the ping's id.
                    payload={"ts": time.time()},
                )
            )
            return
        if command.name in CAPTURE_COMMAND_NAMES:
            # capture.start / capture.stop (engine.capture_command_dispatcher
            # owns validation and replies; behaviour pinned by the M1 tests).
            await dispatch_capture_command(command, self._capture_service, self._send)
            return
        if command.name in NAOMI_COMMAND_NAMES:
            # Additive naomi.say / naomi.cancel surface (engine.voice owns
            # validation, refusal semantics, and replies).
            await dispatch_naomi_command(command, self._voice_streamer, self._send)
            return
        if command.name in MEETING_COMMAND_NAMES:
            # Additive meeting.finalize / meetings.list / meeting.get surface
            # (engine.enhance owns validation, refusal semantics, and replies).
            await dispatch_meeting_command(command, self._finalization_service, self._send)
            return
        if command.name in ASK_COMMAND_NAMES:
            # Additive ask.query surface (engine.ask dispatcher owns it).
            await dispatch_ask_command(command, self._ask_gateway, self._send)
            return
        if command.name in DICTATION_COMMAND_NAMES:
            # Additive dictation.begin/end surface (server-layer dispatcher).
            await dispatch_dictation_command(command, self._dictation_gateway, self._send)
            return
        if command.name in APPROVAL_COMMAND_NAMES:
            # Additive cards.list / card.* surface (server-layer dispatcher).
            await dispatch_approval_command(command, self._approval_gateway, self._send)
            return
        if command.name in DETECTION_COMMAND_NAMES:
            # Additive detection.dismiss surface (engine.detect dispatcher).
            await dispatch_detection_command(command, self._detection_service, self._send)
            return
        if command.name in DEVICES_COMMAND_NAMES:
            # Additive devices.list surface (engine.audio dispatcher).
            await dispatch_devices_command(command, self._device_lister, self._send)
            return
        # Deny by default: anything unrecognised is an explicit error.
        await self._send(
            error_reply(
                command.id,
                ProtocolErrorCode.UNKNOWN_COMMAND,
                f"unknown command name: {command.name!r}",
            )
        )


def _best_effort_frame_id(raw: str) -> str:
    """Try to recover a usable `id` from a rejected frame for correlation.

    Deliberately conservative: only a plain string id of sane length is
    reused; anything else gets a fresh UUID (never reflect unbounded
    untrusted content back to the client).
    """
    import json  # Local import: only needed on the rejection path.

    try:
        decoded = json.loads(raw)
    except (ValueError, UnicodeDecodeError):
        return str(uuid.uuid4())
    if isinstance(decoded, dict):
        frame_id = decoded.get("id")
        if isinstance(frame_id, str) and 0 < len(frame_id) <= 128:
            return frame_id
    return str(uuid.uuid4())
