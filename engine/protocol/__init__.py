"""WebSocket protocol v1 between the engine sidecar and the UI shell.

Purpose: the pinned wire contract — envelope shape, message names, error
codes, and payload models. The UI is built against these exact shapes;
changes here are breaking protocol changes and require a version bump.
Pipeline position: sits between ``engine.server`` (transport) and every
feature module that emits events or answers commands.

Security invariant: every inbound frame is treated as untrusted input and
must pass through ``parse_envelope`` (size cap + strict validation) before
any handler sees it — fail closed, never crash the socket.
"""

from engine.protocol.capture_event_payloads import (
    COMMAND_CAPTURE_START,
    COMMAND_CAPTURE_STOP,
    EVENT_CAPTURE_DEVICE_CHANGED,
    EVENT_CAPTURE_STARTED,
    EVENT_CAPTURE_STOPPED,
    EVENT_TRANSCRIPT_FINAL,
    EVENT_TRANSCRIPT_PARTIAL,
    CaptureStartCommandPayload,
    CaptureStopCommandPayload,
    build_capture_device_changed_payload,
    build_capture_started_payload,
    build_capture_stopped_payload,
    build_transcript_final_payload,
    build_transcript_partial_payload,
)
from engine.protocol.event_broadcast_hub import EventBroadcastHub
from engine.protocol.heartbeat_payload import build_heartbeat_payload
from engine.protocol.meeting_finalization_payloads import (
    COMMAND_MEETING_FINALIZE,
    COMMAND_MEETING_GET,
    COMMAND_MEETINGS_LIST,
    EVENT_ENHANCE_FAILED,
    EVENT_ENHANCE_READY,
    EVENT_ENHANCE_STARTED,
    MeetingFinalizeCommandPayload,
    MeetingGetCommandPayload,
    MeetingsListCommandPayload,
    build_enhance_failed_payload,
    build_enhance_ready_payload,
    build_enhance_started_payload,
)
from engine.protocol.websocket_envelope import (
    MAX_MESSAGE_BYTES,
    PROTOCOL_VERSION,
    Envelope,
    EnvelopeKind,
    ProtocolError,
    ProtocolErrorCode,
    error_reply,
    parse_envelope,
)

__all__ = [
    "COMMAND_CAPTURE_START",
    "COMMAND_CAPTURE_STOP",
    "COMMAND_MEETING_FINALIZE",
    "COMMAND_MEETING_GET",
    "COMMAND_MEETINGS_LIST",
    "EVENT_CAPTURE_DEVICE_CHANGED",
    "EVENT_CAPTURE_STARTED",
    "EVENT_CAPTURE_STOPPED",
    "EVENT_ENHANCE_FAILED",
    "EVENT_ENHANCE_READY",
    "EVENT_ENHANCE_STARTED",
    "EVENT_TRANSCRIPT_FINAL",
    "EVENT_TRANSCRIPT_PARTIAL",
    "MAX_MESSAGE_BYTES",
    "PROTOCOL_VERSION",
    "CaptureStartCommandPayload",
    "CaptureStopCommandPayload",
    "Envelope",
    "EnvelopeKind",
    "EventBroadcastHub",
    "MeetingFinalizeCommandPayload",
    "MeetingGetCommandPayload",
    "MeetingsListCommandPayload",
    "ProtocolError",
    "ProtocolErrorCode",
    "build_capture_device_changed_payload",
    "build_capture_started_payload",
    "build_capture_stopped_payload",
    "build_enhance_failed_payload",
    "build_enhance_ready_payload",
    "build_enhance_started_payload",
    "build_heartbeat_payload",
    "build_transcript_final_payload",
    "build_transcript_partial_payload",
    "error_reply",
    "parse_envelope",
]
