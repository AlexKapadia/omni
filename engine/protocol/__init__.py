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

from engine.protocol.heartbeat_payload import build_heartbeat_payload
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
    "MAX_MESSAGE_BYTES",
    "PROTOCOL_VERSION",
    "Envelope",
    "EnvelopeKind",
    "ProtocolError",
    "ProtocolErrorCode",
    "build_heartbeat_payload",
    "error_reply",
    "parse_envelope",
]
