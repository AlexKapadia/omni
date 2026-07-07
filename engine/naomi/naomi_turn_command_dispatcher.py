"""``naomi.listen.start`` / ``naomi.listen.stop`` dispatch for the WS handler.

Purpose: the ADDITIVE conversation-loop command surface — validates the
untrusted listen payloads and drives the turn orchestrator, keeping the diff
inside ``engine.websocket_connection_handler`` to a single delegation branch
(the same shape as the ask/meeting/voice dispatchers). Turn results flow to
the UI as ``naomi.*`` EVENTS from the orchestrator, not as command replies —
these replies only acknowledge that listening started/stopped.
Pipeline position: called by the connection handler for any command whose
name is in ``NAOMI_LOOP_COMMAND_NAMES``; sits above ``engine.naomi``.

Security invariants: payloads are strictly validated (extra fields
forbidden — deny by default); a missing orchestrator refuses honestly rather
than crashing the socket (fail closed, visibly).
"""

from collections.abc import Awaitable, Callable
from typing import Protocol

from pydantic import ValidationError

from engine.naomi.naomi_turn_protocol_names import (
    COMMAND_NAOMI_LISTEN_START,
    COMMAND_NAOMI_LISTEN_STOP,
    NaomiListenStartPayload,
    NaomiListenStopPayload,
)
from engine.protocol import (
    PROTOCOL_VERSION,
    Envelope,
    EnvelopeKind,
    ProtocolErrorCode,
    error_reply,
)

# The commands this dispatcher owns; the handler routes ONLY these here.
NAOMI_LOOP_COMMAND_NAMES = frozenset({COMMAND_NAOMI_LISTEN_START, COMMAND_NAOMI_LISTEN_STOP})

# Additive error code for loop refusals (string literal beside the pinned
# enum, mirroring the voice dispatcher's voice_error).
NAOMI_LOOP_ERROR_CODE = "naomi_loop_error"

SendFn = Callable[[Envelope], Awaitable[None]]


class NaomiTurnControl(Protocol):
    """The minimal surface the dispatcher drives (the orchestrator satisfies
    it structurally). Declared here so the wiring and tests share one
    contract without a hard dependency on the concrete orchestrator."""

    async def listen_start(self, open_mic: bool) -> None: ...  # pragma: no cover - protocol

    async def listen_stop(self, flush: bool) -> None: ...  # pragma: no cover - protocol

    @property
    def state(self) -> object: ...  # pragma: no cover - protocol


async def dispatch_naomi_loop_command(
    command: Envelope, control: NaomiTurnControl | None, send: SendFn
) -> None:
    """Handle one validated naomi.listen.* command envelope, always replying."""
    if control is None:
        # Loop not wired in this app instance: refuse honestly (fail closed).
        await send(_loop_error_reply(command.id, "Naomi's conversation loop is not available"))
        return
    if command.name == COMMAND_NAOMI_LISTEN_START:
        await _handle_start(command, control, send)
        return
    if command.name == COMMAND_NAOMI_LISTEN_STOP:
        await _handle_stop(command, control, send)
        return
    # Unreachable while the handler routes by NAOMI_LOOP_COMMAND_NAMES; keep
    # the deny-by-default reply so a routing bug can never go silent.
    await send(
        error_reply(
            command.id,
            ProtocolErrorCode.UNKNOWN_COMMAND,
            f"unknown naomi command: {command.name!r}",
        )
    )


async def _handle_start(command: Envelope, control: NaomiTurnControl, send: SendFn) -> None:
    try:
        payload = NaomiListenStartPayload.model_validate(command.payload)
    except ValidationError:
        await send(
            error_reply(
                command.id, ProtocolErrorCode.INVALID_PAYLOAD, "naomi.listen.start payload invalid"
            )
        )
        return
    await control.listen_start(payload.open_mic)
    await send(_ok_reply(command.id, {"state": str(control.state)}))


async def _handle_stop(command: Envelope, control: NaomiTurnControl, send: SendFn) -> None:
    try:
        payload = NaomiListenStopPayload.model_validate(command.payload)
    except ValidationError:
        await send(
            error_reply(
                command.id, ProtocolErrorCode.INVALID_PAYLOAD, "naomi.listen.stop payload invalid"
            )
        )
        return
    await control.listen_stop(payload.flush)
    await send(_ok_reply(command.id, {"state": str(control.state)}))


def _ok_reply(reply_id: str, payload: dict[str, object]) -> Envelope:
    return Envelope(
        v=PROTOCOL_VERSION,
        kind=EnvelopeKind.REPLY,
        name="ok",
        id=reply_id,
        payload=dict(payload),
    )


def _loop_error_reply(reply_id: str, message: str) -> Envelope:
    return Envelope(
        v=PROTOCOL_VERSION,
        kind=EnvelopeKind.REPLY,
        name="error",
        id=reply_id,
        payload={"code": NAOMI_LOOP_ERROR_CODE, "message": message},
    )
