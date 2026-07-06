"""``devices.list`` dispatch for the WS handler.

Purpose: the ADDITIVE device-listing command surface — validates the
(empty) payload, runs the blocking enumeration off the event loop, and
answers with the house reply shapes (``ok`` / ``error``), keeping the diff
inside ``engine.websocket_connection_handler`` to a single delegation
branch (same pattern as the meeting/naomi dispatchers).
Pipeline position: called by the connection handler for any command whose
name is in ``DEVICES_COMMAND_NAMES``; speaks only ``engine.protocol``
envelopes.

Security invariants:
- Strict payload validation (extra fields forbidden) — deny by default.
- Enumeration failures become structured ``error`` replies with a stable
  additive code; the socket never crashes and no failure fabricates a
  device list (fail closed, visibly).
"""

import asyncio
from collections.abc import Awaitable, Callable

from pydantic import ValidationError

from engine.protocol import (
    COMMAND_DEVICES_LIST,
    PROTOCOL_VERSION,
    AudioDeviceDescription,
    DevicesListCommandPayload,
    Envelope,
    EnvelopeKind,
    ProtocolErrorCode,
    build_devices_list_payload,
    error_reply,
)

# The commands this dispatcher owns; the handler routes ONLY these here.
DEVICES_COMMAND_NAMES = frozenset({COMMAND_DEVICES_LIST})

# Additive error code (string literal beside the pinned enum, mirroring the
# meeting dispatcher's `finalize_error`).
DEVICES_ERROR_CODE = "devices_error"

SendFn = Callable[[Envelope], Awaitable[None]]
DeviceLister = Callable[[], list[AudioDeviceDescription]]


def _ok_reply(reply_id: str, payload: dict[str, object]) -> Envelope:
    return Envelope(
        v=PROTOCOL_VERSION, kind=EnvelopeKind.REPLY, name="ok", id=reply_id, payload=dict(payload)
    )


def _devices_error_reply(reply_id: str, message: str) -> Envelope:
    return Envelope(
        v=PROTOCOL_VERSION,
        kind=EnvelopeKind.REPLY,
        name="error",
        id=reply_id,
        payload={"code": DEVICES_ERROR_CODE, "message": message},
    )


async def dispatch_devices_command(
    command: Envelope, lister: DeviceLister | None, send: SendFn
) -> None:
    """Handle one validated devices.* command envelope, always replying."""
    try:
        DevicesListCommandPayload.model_validate(command.payload)
    except ValidationError:
        await send(
            error_reply(
                command.id,
                ProtocolErrorCode.INVALID_PAYLOAD,
                "devices.list payload failed validation",
            )
        )
        return
    if lister is None:
        # Device listing not wired in this app instance: refuse honestly.
        await send(_devices_error_reply(command.id, "device listing is not available"))
        return
    try:
        # PortAudio enumeration is blocking (~tens of ms): off the loop so
        # heartbeats and live transcription never stall behind it.
        devices = await asyncio.to_thread(lister)
    except Exception as exc:  # fail closed, visibly: no fabricated list
        await send(_devices_error_reply(command.id, f"could not enumerate audio devices: {exc}"))
        return
    await send(_ok_reply(command.id, build_devices_list_payload(devices)))
