"""``capture.start`` / ``capture.stop`` dispatch for the WS handler.

Purpose: the M1 capture lifecycle command surface — validates untrusted
payloads, drives ``LiveCaptureService``, and answers with the house reply
shapes (``ok`` / ``error``). Split out of the connection handler at the
reconciliation pass so the handler stays pure routing (same shape as the
meeting/naomi/ask/dictation dispatchers); behaviour is unchanged and pinned
by the existing capture command tests.
Pipeline position: called by the connection handler for any command whose
name is in ``CAPTURE_COMMAND_NAMES``; speaks only ``engine.protocol``
envelopes.

Security invariants:
- Strict payload validation (extra fields forbidden) — deny by default; a
  malformed frame never reaches the capture service.
- Capture failures become structured ``capture_error`` replies; the socket
  never crashes and no failure is silent (fail closed, visibly).
"""

from collections.abc import Awaitable, Callable

from pydantic import ValidationError

from engine.protocol import (
    COMMAND_CAPTURE_START,
    COMMAND_CAPTURE_STOP,
    PROTOCOL_VERSION,
    CaptureStartCommandPayload,
    CaptureStopCommandPayload,
    Envelope,
    EnvelopeKind,
    ProtocolErrorCode,
    error_reply,
)
from engine.stt.capture_model_loading import CaptureServiceError
from engine.stt.live_capture_service import LiveCaptureService

# The commands this dispatcher owns; the handler routes ONLY these here.
CAPTURE_COMMAND_NAMES = frozenset({COMMAND_CAPTURE_START, COMMAND_CAPTURE_STOP})

SendFn = Callable[[Envelope], Awaitable[None]]


def _ok_reply(reply_id: str, payload: dict[str, object]) -> Envelope:
    """The standard success reply: name `ok`, id echoing the command."""
    return Envelope(
        v=PROTOCOL_VERSION, kind=EnvelopeKind.REPLY, name="ok", id=reply_id, payload=dict(payload)
    )


async def dispatch_capture_command(
    command: Envelope, capture_service: LiveCaptureService, send: SendFn
) -> None:
    """Handle one validated capture.* command envelope, always replying."""
    if command.name == COMMAND_CAPTURE_START:
        await _handle_capture_start(command, capture_service, send)
        return
    await _handle_capture_stop(command, capture_service, send)


async def _handle_capture_start(
    command: Envelope, capture_service: LiveCaptureService, send: SendFn
) -> None:
    """capture.start → ok {meeting_id} or a structured error reply."""
    try:
        # Strict payload validation (extra fields forbidden) — the command
        # payload is untrusted input like everything inbound.
        payload = CaptureStartCommandPayload.model_validate(command.payload)
    except ValidationError:
        await send(
            error_reply(
                command.id,
                ProtocolErrorCode.INVALID_PAYLOAD,
                "capture.start payload failed validation",
            )
        )
        return
    try:
        meeting_id = await capture_service.start(payload.title)
    except CaptureServiceError as exc:
        # Fail closed with a correlatable, structured reason.
        await send(error_reply(command.id, ProtocolErrorCode.CAPTURE_ERROR, str(exc)))
        return
    await send(_ok_reply(command.id, {"meeting_id": meeting_id}))


async def _handle_capture_stop(
    command: Envelope, capture_service: LiveCaptureService, send: SendFn
) -> None:
    """capture.stop → ok {meeting_id} or a structured error reply."""
    try:
        CaptureStopCommandPayload.model_validate(command.payload)
    except ValidationError:
        await send(
            error_reply(
                command.id,
                ProtocolErrorCode.INVALID_PAYLOAD,
                "capture.stop payload failed validation",
            )
        )
        return
    try:
        meeting_id = await capture_service.stop()
    except CaptureServiceError as exc:
        await send(error_reply(command.id, ProtocolErrorCode.CAPTURE_ERROR, str(exc)))
        return
    await send(_ok_reply(command.id, {"meeting_id": meeting_id}))
