"""naomi.say / naomi.cancel command dispatch for the WS connection handler.

Purpose: the ADDITIVE command surface — validates untrusted payloads,
invokes the TtsPlaybackStreamer, and answers with the house reply shapes
(``ok`` / ``error``), keeping the diff inside
``engine.websocket_connection_handler`` to a single delegation branch.
Pipeline position: called by the connection handler for any command whose
name is in NAOMI_COMMAND_NAMES; speaks only ``engine.protocol`` envelopes.

Security invariants:
- Payloads are strictly validated (extra fields forbidden) — deny by default.
- Voice refusals (kill switch, missing key) become structured ``error``
  replies with the code ``voice_error``; the socket never crashes and the
  refusal is honest, never silent (fail closed, visibly).
"""

from collections.abc import Awaitable, Callable

from pydantic import ValidationError

from engine.protocol import (
    PROTOCOL_VERSION,
    Envelope,
    EnvelopeKind,
    ProtocolErrorCode,
    error_reply,
)
from engine.voice.naomi_voice_event_payloads import (
    COMMAND_NAOMI_CANCEL,
    COMMAND_NAOMI_SAY,
    NaomiCancelCommandPayload,
    NaomiSayCommandPayload,
)
from engine.voice.tts_playback_streamer import TtsPlaybackStreamer
from engine.voice.voice_errors import VoiceEgressBlockedError, VoiceNotConfiguredError

# The commands this dispatcher owns; the handler routes ONLY these here.
NAOMI_COMMAND_NAMES = frozenset({COMMAND_NAOMI_SAY, COMMAND_NAOMI_CANCEL})

# Additive error code for voice refusals/failures. A string literal, not an
# enum extension — engine.protocol is pinned and owned elsewhere.
VOICE_ERROR_CODE = "voice_error"

SendFn = Callable[[Envelope], Awaitable[None]]


def _voice_error_reply(reply_id: str, message: str) -> Envelope:
    """An ``error`` reply carrying the additive voice_error code."""
    return Envelope(
        v=PROTOCOL_VERSION,
        kind=EnvelopeKind.REPLY,
        name="error",
        id=reply_id,
        payload={"code": VOICE_ERROR_CODE, "message": message},
    )


def _ok_reply(reply_id: str, payload: dict[str, object]) -> Envelope:
    return Envelope(
        v=PROTOCOL_VERSION,
        kind=EnvelopeKind.REPLY,
        name="ok",
        id=reply_id,
        payload=dict(payload),
    )


async def dispatch_naomi_command(
    command: Envelope,
    streamer: TtsPlaybackStreamer | None,
    send: SendFn,
) -> None:
    """Handle one validated naomi.* command envelope, always replying."""
    if streamer is None:
        # Voice not wired in this build/app instance: refuse honestly.
        await send(_voice_error_reply(command.id, "voice is not available in this engine build"))
        return
    if command.name == COMMAND_NAOMI_SAY:
        await _handle_say(command, streamer, send)
        return
    if command.name == COMMAND_NAOMI_CANCEL:
        await _handle_cancel(command, streamer, send)
        return
    # Unreachable while the handler routes by NAOMI_COMMAND_NAMES; keep the
    # deny-by-default reply anyway so a routing bug cannot go silent.
    await send(
        error_reply(
            command.id,
            ProtocolErrorCode.UNKNOWN_COMMAND,
            f"unknown naomi command: {command.name!r}",
        )
    )


async def _handle_say(command: Envelope, streamer: TtsPlaybackStreamer, send: SendFn) -> None:
    """naomi.say → ok {context_id} or a structured refusal."""
    try:
        payload = NaomiSayCommandPayload.model_validate(command.payload)
    except ValidationError:
        await send(
            error_reply(
                command.id,
                ProtocolErrorCode.INVALID_PAYLOAD,
                "naomi.say payload failed validation",
            )
        )
        return
    affect = None if payload.affect is None else (payload.affect.v, payload.affect.a)
    try:
        context_id = await streamer.say(payload.text, affect)
    except (VoiceEgressBlockedError, VoiceNotConfiguredError) as exc:
        # Fail closed with the honest reason (kill switch / missing key —
        # message never contains key material by construction).
        await send(_voice_error_reply(command.id, str(exc)))
        return
    await send(_ok_reply(command.id, {"context_id": context_id}))


async def _handle_cancel(command: Envelope, streamer: TtsPlaybackStreamer, send: SendFn) -> None:
    """naomi.cancel → ok {cancelled_context_id} (null when nothing spoke)."""
    try:
        NaomiCancelCommandPayload.model_validate(command.payload)
    except ValidationError:
        await send(
            error_reply(
                command.id,
                ProtocolErrorCode.INVALID_PAYLOAD,
                "naomi.cancel payload failed validation",
            )
        )
        return
    cancelled = await streamer.cancel()
    await send(_ok_reply(command.id, {"cancelled_context_id": cancelled}))
