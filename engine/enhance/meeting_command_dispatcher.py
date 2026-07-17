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

import contextlib
from collections.abc import Awaitable, Callable

from pydantic import ValidationError

from engine.enhance.meeting_finalization_result_types import FinalizeRefusedError
from engine.enhance.meeting_finalization_service import MeetingFinalizationService
from engine.enhance.meeting_summary_presenter import (
    meeting_detail_payload,
    meeting_summary_payload,
)
from engine.protocol import (
    COMMAND_IMPORT_MEDIA,
    COMMAND_MEETING_DELETE,
    COMMAND_MEETING_EXPORT,
    COMMAND_MEETING_FINALIZE,
    COMMAND_MEETING_GET,
    COMMAND_MEETING_RETRANSCRIBE,
    COMMAND_MEETING_TEXT_REPLACE,
    COMMAND_MEETINGS_LIST,
    COMMAND_TRANSCRIPT_SEGMENT_UPDATE,
    PROTOCOL_VERSION,
    Envelope,
    EnvelopeKind,
    ImportMediaCommandPayload,
    MeetingDeleteCommandPayload,
    MeetingExportCommandPayload,
    MeetingFinalizeCommandPayload,
    MeetingGetCommandPayload,
    MeetingRetranscribeCommandPayload,
    MeetingsListCommandPayload,
    MeetingTextReplacePayload,
    ProtocolErrorCode,
    TranscriptSegmentUpdatePayload,
    error_reply,
)
from engine.storage.app_settings_repository import SETTING_SPEAKER_IDENTITY, read_setting
from engine.storage.sqlite_connection import open_sqlite_connection
from engine.storage.sqlite_migrations_runner import apply_migrations

# The commands this dispatcher owns; the handler routes ONLY these here.
MEETING_COMMAND_NAMES = frozenset(
    {
        COMMAND_MEETING_FINALIZE,
        COMMAND_MEETINGS_LIST,
        COMMAND_MEETING_GET,
        COMMAND_MEETING_EXPORT,
        COMMAND_TRANSCRIPT_SEGMENT_UPDATE,
        COMMAND_IMPORT_MEDIA,
        COMMAND_MEETING_RETRANSCRIBE,
        COMMAND_MEETING_TEXT_REPLACE,
        COMMAND_MEETING_DELETE,
    }
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
    if command.name == COMMAND_MEETING_EXPORT:
        await _handle_export(command, service, send)
        return
    if command.name == COMMAND_TRANSCRIPT_SEGMENT_UPDATE:
        await _handle_segment_update(command, service, send)
        return
    if command.name == COMMAND_IMPORT_MEDIA:
        await _handle_import_media(command, service, send)
        return
    if command.name == COMMAND_MEETING_RETRANSCRIBE:
        await _handle_retranscribe(command, service, send)
        return
    if command.name == COMMAND_MEETING_TEXT_REPLACE:
        await _handle_text_replace(command, service, send)
        return
    if command.name == COMMAND_MEETING_DELETE:
        await _handle_delete(command, service, send)
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
    row, segments, extraction = found
    identity = "Me"
    with contextlib.suppress(Exception):
        await apply_migrations(service.db_path, service.migrations_dir)
        connection = await open_sqlite_connection(service.db_path)
        try:
            raw = await read_setting(connection, SETTING_SPEAKER_IDENTITY)
            if isinstance(raw, str) and raw.strip():
                identity = raw.strip()
        finally:
            await connection.close()
    from engine.enhance.meeting_kept_audio import meeting_has_kept_audio

    await send(
        _ok_reply(
            command.id,
            meeting_detail_payload(
                row,
                segments,
                extraction,
                speaker_identity=identity,
                has_kept_audio=meeting_has_kept_audio(row.id),
            ),
        )
    )


async def _handle_export(
    command: Envelope, service: MeetingFinalizationService, send: SendFn
) -> None:
    try:
        payload = MeetingExportCommandPayload.model_validate(command.payload)
    except ValidationError:
        await send(
            error_reply(
                command.id,
                ProtocolErrorCode.INVALID_PAYLOAD,
                "meeting.export payload failed validation",
            )
        )
        return
    content = await service.export_transcript(payload.meeting_id, payload.format)
    if content is None:
        await send(
            _typed_error_reply(
                command.id, NOT_FOUND_ERROR_CODE, f"meeting {payload.meeting_id!r} does not exist"
            )
        )
        return
    await send(_ok_reply(command.id, content))


async def _handle_segment_update(
    command: Envelope, service: MeetingFinalizationService, send: SendFn
) -> None:
    try:
        payload = TranscriptSegmentUpdatePayload.model_validate(command.payload)
    except ValidationError:
        await send(
            error_reply(
                command.id,
                ProtocolErrorCode.INVALID_PAYLOAD,
                "transcript.segment.update payload failed validation",
            )
        )
        return
    changed = await service.update_transcript_segment(
        payload.meeting_id, payload.segment_id, payload.text
    )
    if not changed:
        await send(
            _typed_error_reply(
                command.id, NOT_FOUND_ERROR_CODE, "segment not found or meeting still live"
            )
        )
        return
    await send(_ok_reply(command.id, {"segment_id": payload.segment_id}))


async def _handle_import_media(
    command: Envelope, service: MeetingFinalizationService, send: SendFn
) -> None:
    try:
        payload = ImportMediaCommandPayload.model_validate(command.payload)
    except ValidationError:
        await send(
            error_reply(
                command.id,
                ProtocolErrorCode.INVALID_PAYLOAD,
                "import.media payload failed validation",
            )
        )
        return
    from engine.import_.media_import_service import import_media_file
    from engine.protocol.meeting_finalization_payloads import (
        EVENT_IMPORT_MEDIA_PROGRESS,
        build_import_media_progress_payload,
    )

    hub = service._hub

    async def on_progress(stage: str, fraction: float) -> None:
        await hub.broadcast_event(
            EVENT_IMPORT_MEDIA_PROGRESS,
            build_import_media_progress_payload(stage, fraction),
        )

    try:
        meeting_id = await import_media_file(
            service.db_path,
            service.migrations_dir,
            payload.path,
            payload.title,
            identify_speakers=payload.identify_speakers,
            on_progress=on_progress,
        )
    except Exception as exc:
        await send(_typed_error_reply(command.id, FINALIZE_ERROR_CODE, str(exc)))
        return
    await send(_ok_reply(command.id, {"meeting_id": meeting_id}))


async def _handle_retranscribe(
    command: Envelope, service: MeetingFinalizationService, send: SendFn
) -> None:
    try:
        payload = MeetingRetranscribeCommandPayload.model_validate(command.payload)
    except ValidationError:
        await send(
            error_reply(
                command.id,
                ProtocolErrorCode.INVALID_PAYLOAD,
                "meeting.retranscribe payload failed validation",
            )
        )
        return
    try:
        await service.retranscribe(payload.meeting_id)
    except Exception as exc:
        await send(_typed_error_reply(command.id, FINALIZE_ERROR_CODE, str(exc)))
        return
    await send(_ok_reply(command.id, {"meeting_id": payload.meeting_id}))


async def _handle_text_replace(
    command: Envelope, service: MeetingFinalizationService, send: SendFn
) -> None:
    try:
        payload = MeetingTextReplacePayload.model_validate(command.payload)
    except ValidationError:
        await send(
            error_reply(
                command.id,
                ProtocolErrorCode.INVALID_PAYLOAD,
                "meeting.text.replace payload failed validation",
            )
        )
        return
    result = await service.replace_meeting_text(
        payload.meeting_id, payload.find, payload.replace, payload.target
    )
    if result is None:
        await send(
            _typed_error_reply(
                command.id, NOT_FOUND_ERROR_CODE, f"meeting {payload.meeting_id!r} does not exist"
            )
        )
        return
    reply_payload: dict[str, object] = dict(result)
    await send(_ok_reply(command.id, reply_payload))


async def _handle_delete(
    command: Envelope, service: MeetingFinalizationService, send: SendFn
) -> None:
    """meeting.delete → ok {deleted, vault_note_kept} or not_found.

    Soft-deletes the Library row and wipes kept audio + transcript segments.
    The vault note is left on purpose (privacy is about recordings).
    """
    try:
        payload = MeetingDeleteCommandPayload.model_validate(command.payload)
    except ValidationError:
        await send(
            error_reply(
                command.id,
                ProtocolErrorCode.INVALID_PAYLOAD,
                "meeting.delete payload failed validation",
            )
        )
        return
    result = await service.delete_meeting(payload.meeting_id)
    if result is None:
        await send(
            _typed_error_reply(
                command.id, NOT_FOUND_ERROR_CODE, f"meeting {payload.meeting_id!r} does not exist"
            )
        )
        return
    await send(_ok_reply(command.id, result))
