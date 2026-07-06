"""meeting.finalize / meetings.list / meeting.get dispatch for the WS handler.

Purpose: the ADDITIVE M2 command surface — validates untrusted payloads,
invokes the finalization service, and answers with the house reply shapes
(``ok`` / ``error``), keeping the diff inside
``engine.websocket_connection_handler`` to a single delegation branch
(same pattern as the naomi voice dispatcher).
Pipeline position: called by the connection handler for any command whose
name is in MEETING_COMMAND_NAMES; speaks only ``engine.protocol`` envelopes.

Security invariants:
- Payloads are strictly validated (extra fields forbidden, hard bounds) —
  deny by default; a malformed frame never reaches the service.
- Refusals (unknown meeting, duplicate finalize, unconfigured vault, no
  keys) become structured ``error`` replies with stable additive codes;
  the socket never crashes and no refusal is silent (fail closed, visibly).
"""

from collections.abc import Awaitable, Callable

from pydantic import ValidationError

from engine.enhance.meeting_finalization_result_types import FinalizeRefusedError
from engine.enhance.meeting_finalization_service import MeetingFinalizationService
from engine.enhance.meeting_summary_presenter import (
    meeting_detail_payload,
    meeting_summary_payload,
)
from engine.protocol import (
    COMMAND_MEETING_FINALIZE,
    COMMAND_MEETING_GET,
    COMMAND_MEETINGS_LIST,
    PROTOCOL_VERSION,
    Envelope,
    EnvelopeKind,
    MeetingFinalizeCommandPayload,
    MeetingGetCommandPayload,
    MeetingsListCommandPayload,
    ProtocolErrorCode,
    error_reply,
)

# The commands this dispatcher owns; the handler routes ONLY these here.
MEETING_COMMAND_NAMES = frozenset(
    {COMMAND_MEETING_FINALIZE, COMMAND_MEETINGS_LIST, COMMAND_MEETING_GET}
)

# Additive error codes (string literals, not enum extensions — the pinned
# ProtocolErrorCode enum is owned by engine.protocol; additions ride beside
# it, mirroring the voice dispatcher's `voice_error`).
FINALIZE_ERROR_CODE = "finalize_error"
NOT_FOUND_ERROR_CODE = "not_found"

SendFn = Callable[[Envelope], Awaitable[None]]


def _typed_error_reply(reply_id: str, code: str, message: str) -> Envelope:
    """An ``error`` reply carrying one of the additive M2 codes."""
    return Envelope(
        v=PROTOCOL_VERSION,
        kind=EnvelopeKind.REPLY,
        name="error",
        id=reply_id,
        payload={"code": code, "message": message},
    )


def _ok_reply(reply_id: str, payload: dict[str, object]) -> Envelope:
    return Envelope(
        v=PROTOCOL_VERSION,
        kind=EnvelopeKind.REPLY,
        name="ok",
        id=reply_id,
        payload=dict(payload),
    )


async def dispatch_meeting_command(
    command: Envelope,
    service: MeetingFinalizationService | None,
    send: SendFn,
) -> None:
    """Handle one validated meeting.* command envelope, always replying."""
    if service is None:
        # Finalization not wired in this app instance: refuse honestly.
        await send(
            _typed_error_reply(
                command.id, FINALIZE_ERROR_CODE, "meeting library is not available"
            )
        )
        return
    if command.name == COMMAND_MEETING_FINALIZE:
        await _handle_finalize(command, service, send)
        return
    if command.name == COMMAND_MEETINGS_LIST:
        await _handle_list(command, service, send)
        return
    if command.name == COMMAND_MEETING_GET:
        await _handle_get(command, service, send)
        return
    # Unreachable while the handler routes by MEETING_COMMAND_NAMES; keep
    # the deny-by-default reply so a routing bug cannot go silent.
    await send(
        error_reply(
            command.id,
            ProtocolErrorCode.UNKNOWN_COMMAND,
            f"unknown meeting command: {command.name!r}",
        )
    )


async def _handle_finalize(
    command: Envelope, service: MeetingFinalizationService, send: SendFn
) -> None:
    """meeting.finalize → ok {note_path, ...} or a structured refusal.

    The reply is sent AFTER the run completes (the enhance.* events stream
    progress meanwhile); heartbeats ride their own task so the socket stays
    demonstrably alive during the model calls.
    """
    try:
        payload = MeetingFinalizeCommandPayload.model_validate(command.payload)
    except ValidationError:
        await send(
            error_reply(
                command.id,
                ProtocolErrorCode.INVALID_PAYLOAD,
                "meeting.finalize payload failed validation",
            )
        )
        return
    try:
        result = await service.finalize(payload.meeting_id, payload.notepad_text, payload.template)
    except FinalizeRefusedError as exc:
        # Fail closed with the honest, plain-voice reason (no key material,
        # no raw model output — refusal messages are ours by construction).
        await send(_typed_error_reply(command.id, FINALIZE_ERROR_CODE, str(exc)))
        return
    await send(_ok_reply(command.id, result.to_payload()))


async def _handle_list(
    command: Envelope, service: MeetingFinalizationService, send: SendFn
) -> None:
    """meetings.list → ok {meetings: [...]} (empty list when none)."""
    try:
        MeetingsListCommandPayload.model_validate(command.payload)
    except ValidationError:
        await send(
            error_reply(
                command.id,
                ProtocolErrorCode.INVALID_PAYLOAD,
                "meetings.list payload failed validation",
            )
        )
        return
    rows = await service.list_meetings()
    await send(_ok_reply(command.id, {"meetings": [meeting_summary_payload(r) for r in rows]}))


async def _handle_get(
    command: Envelope, service: MeetingFinalizationService, send: SendFn
) -> None:
    """meeting.get → ok {meeting detail} or not_found."""
    try:
        payload = MeetingGetCommandPayload.model_validate(command.payload)
    except ValidationError:
        await send(
            error_reply(
                command.id,
                ProtocolErrorCode.INVALID_PAYLOAD,
                "meeting.get payload failed validation",
            )
        )
        return
    found = await service.get_meeting(payload.meeting_id)
    if found is None:
        # Deny by default: an unknown id is an explicit, correlatable error.
        await send(
            _typed_error_reply(
                command.id, NOT_FOUND_ERROR_CODE, f"meeting {payload.meeting_id!r} does not exist"
            )
        )
        return
    row, segments = found
    await send(_ok_reply(command.id, meeting_detail_payload(row, segments)))
