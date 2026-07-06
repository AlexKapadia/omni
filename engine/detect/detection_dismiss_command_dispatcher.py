"""``detection.dismiss`` dispatch for the WS handler.

Purpose: the ADDITIVE M6 command surface — validates the untrusted dismiss
payload and forwards the dedupe key to the detection service's cooldown,
keeping the diff inside ``engine.websocket_connection_handler`` to a single
delegation branch (same pattern as the meeting/naomi dispatchers).
Pipeline position: called by the connection handler for any command whose
name is in ``DETECTION_COMMAND_NAMES``; drives
``DetectionService.dismiss_suggestion``.

Security invariants:
- Strict payload validation (extra fields forbidden, bounded key) — deny
  by default; a malformed frame never reaches the service.
- Dismissal only ever SUPPRESSES suggestions; it can neither start nor
  stop capture (approval-before-execute stays with the user).
"""

from collections.abc import Awaitable, Callable

from pydantic import ValidationError

from engine.detect.detection_service import DetectionService
from engine.protocol import (
    COMMAND_DETECTION_DISMISS,
    PROTOCOL_VERSION,
    DetectionDismissCommandPayload,
    Envelope,
    EnvelopeKind,
    ProtocolErrorCode,
    error_reply,
)

# The commands this dispatcher owns; the handler routes ONLY these here.
DETECTION_COMMAND_NAMES = frozenset({COMMAND_DETECTION_DISMISS})

# Additive error code (string literal beside the pinned enum, mirroring the
# meeting dispatcher's `finalize_error`).
DETECTION_ERROR_CODE = "detection_error"

SendFn = Callable[[Envelope], Awaitable[None]]


async def dispatch_detection_command(
    command: Envelope, service: DetectionService | None, send: SendFn
) -> None:
    """Handle one validated detection.* command envelope, always replying."""
    try:
        payload = DetectionDismissCommandPayload.model_validate(command.payload)
    except ValidationError:
        await send(
            error_reply(
                command.id,
                ProtocolErrorCode.INVALID_PAYLOAD,
                "detection.dismiss payload failed validation",
            )
        )
        return
    if service is None:
        # Detection not wired in this app instance: refuse honestly.
        await send(
            Envelope(
                v=PROTOCOL_VERSION,
                kind=EnvelopeKind.REPLY,
                name="error",
                id=command.id,
                payload={"code": DETECTION_ERROR_CODE, "message": "detection is not available"},
            )
        )
        return
    service.dismiss_suggestion(payload.dedupe_key)
    await send(
        Envelope(v=PROTOCOL_VERSION, kind=EnvelopeKind.REPLY, name="ok", id=command.id, payload={})
    )
