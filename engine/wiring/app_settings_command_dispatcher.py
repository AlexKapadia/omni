"""``settings.get`` / ``settings.update`` / ``setup.status`` WS dispatch.

Purpose: validates untrusted settings-surface payloads, drives
:class:`AppSettingsCommandGateway`, and answers with the house reply shapes
(``ok`` / typed ``error``) — same shape as every other dispatcher.
Pipeline position: called by the connection handler for any command whose
name is in ``SETTINGS_COMMAND_NAMES``; speaks only ``engine.protocol``
envelopes.

Security invariants:
- Strict payload validation (extra fields forbidden) — deny by default.
- Refused updates become structured ``settings_error`` replies; nothing is
  persisted on refusal and the socket never crashes (fail closed, visibly).
"""

import logging
from collections.abc import Awaitable, Callable

from pydantic import ValidationError

from engine.protocol import (
    COMMAND_SETTINGS_GET,
    COMMAND_SETTINGS_UPDATE,
    COMMAND_SETUP_STATUS,
    PROTOCOL_VERSION,
    Envelope,
    EnvelopeKind,
    ProtocolErrorCode,
    SettingsGetCommandPayload,
    SettingsUpdateCommandPayload,
    SetupStatusCommandPayload,
    error_reply,
)
from engine.wiring.app_settings_command_gateway import (
    AppSettingsCommandGateway,
    SettingsCommandRefused,
)

logger = logging.getLogger(__name__)

# The commands this dispatcher owns; the handler routes ONLY these here.
SETTINGS_COMMAND_NAMES = frozenset(
    {COMMAND_SETTINGS_GET, COMMAND_SETTINGS_UPDATE, COMMAND_SETUP_STATUS}
)

# Additive error code (string literal beside the pinned enum, mirroring the
# dictation dispatcher's `dictation_error`).
SETTINGS_ERROR_CODE = "settings_error"

SendFn = Callable[[Envelope], Awaitable[None]]


def _ok_reply(reply_id: str, payload: dict[str, object]) -> Envelope:
    return Envelope(
        v=PROTOCOL_VERSION, kind=EnvelopeKind.REPLY, name="ok", id=reply_id, payload=payload
    )


def _settings_error_reply(reply_id: str, message: str) -> Envelope:
    return Envelope(
        v=PROTOCOL_VERSION,
        kind=EnvelopeKind.REPLY,
        name="error",
        id=reply_id,
        payload={"code": SETTINGS_ERROR_CODE, "message": message},
    )


async def dispatch_settings_command(
    command: Envelope, gateway: AppSettingsCommandGateway | None, send: SendFn
) -> None:
    """Handle one validated settings.* / setup.status command, always replying."""
    if gateway is None:
        # Settings not wired in this app instance: refuse honestly.
        await send(_settings_error_reply(command.id, "settings are not available"))
        return
    try:
        if command.name == COMMAND_SETTINGS_GET:
            SettingsGetCommandPayload.model_validate(command.payload)
            await send(_ok_reply(command.id, await gateway.get_settings_payload()))
            return
        if command.name == COMMAND_SETUP_STATUS:
            SetupStatusCommandPayload.model_validate(command.payload)
            await send(_ok_reply(command.id, await gateway.setup_status_payload()))
            return
        payload = SettingsUpdateCommandPayload.model_validate(command.payload)
    except ValidationError:
        await send(
            error_reply(
                command.id,
                ProtocolErrorCode.INVALID_PAYLOAD,
                f"{command.name} payload failed validation",
            )
        )
        return
    try:
        applied = await gateway.update_settings(dict(payload.values))
    except SettingsCommandRefused as exc:
        # Fail closed with the plain-voice reason; nothing was persisted.
        await send(_settings_error_reply(command.id, str(exc)))
        return
    except Exception:
        logger.exception("settings.update failed")
        await send(_settings_error_reply(command.id, "the settings update failed"))
        return
    await send(_ok_reply(command.id, {"applied": applied}))
