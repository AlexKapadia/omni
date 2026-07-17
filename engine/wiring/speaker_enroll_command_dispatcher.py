"""``speaker.enroll`` — save display name + optional voice profile."""

from __future__ import annotations

import base64
import logging
from collections.abc import Awaitable, Callable
from pathlib import Path

from pydantic import ValidationError

from engine.audio.audio_frame_types import PIPELINE_SAMPLE_RATE
from engine.protocol import (
    PROTOCOL_VERSION,
    Envelope,
    EnvelopeKind,
    ProtocolErrorCode,
    error_reply,
)
from engine.protocol.speaker_enroll_payloads import (
    COMMAND_SPEAKER_ENROLL,
    SpeakerEnrollCommandPayload,
)
from engine.storage.app_settings_repository import (
    SETTING_SPEAKER_IDENTITY,
    SETTING_SPEAKER_VOICE_EMBEDDING,
    write_setting,
)
from engine.storage.sqlite_connection import open_sqlite_connection
from engine.storage.sqlite_migrations_runner import apply_migrations
from engine.stt.speaker_voice_profile import (
    decode_wav_pcm16_mono_16k,
    embedding_to_json,
    extract_voice_embedding,
)
from engine.wiring.settings_value_validation import validate_settings_values

logger = logging.getLogger(__name__)

SPEAKER_COMMAND_NAMES = frozenset({COMMAND_SPEAKER_ENROLL})
SPEAKER_ERROR_CODE = "speaker_error"

SendFn = Callable[[Envelope], Awaitable[None]]


def _ok_reply(reply_id: str, payload: dict[str, object]) -> Envelope:
    return Envelope(
        v=PROTOCOL_VERSION, kind=EnvelopeKind.REPLY, name="ok", id=reply_id, payload=payload
    )


def _speaker_error_reply(reply_id: str, message: str) -> Envelope:
    return Envelope(
        v=PROTOCOL_VERSION,
        kind=EnvelopeKind.REPLY,
        name="error",
        id=reply_id,
        payload={"code": SPEAKER_ERROR_CODE, "message": message},
    )


class SpeakerEnrollCommandGateway:
    def __init__(self, db_path: Path, migrations_dir: Path) -> None:
        self._db_path = db_path
        self._migrations_dir = migrations_dir

    async def enroll(self, display_name: str, audio_wav_base64: str | None) -> dict[str, object]:
        values: dict[str, object] = {SETTING_SPEAKER_IDENTITY: display_name.strip()}
        embedding_json: str | None = None
        if audio_wav_base64:
            try:
                wav_bytes = base64.b64decode(audio_wav_base64, validate=True)
                samples = decode_wav_pcm16_mono_16k(wav_bytes)
                if samples.size < PIPELINE_SAMPLE_RATE // 2:
                    raise ValueError("voice sample is too short — speak for at least one second")
                embedding_json = embedding_to_json(extract_voice_embedding(samples))
            except Exception as exc:
                raise ValueError(str(exc)) from exc
        normalized = validate_settings_values(values)
        await apply_migrations(self._db_path, self._migrations_dir)
        connection = await open_sqlite_connection(self._db_path)
        try:
            await write_setting(
                connection, SETTING_SPEAKER_IDENTITY, normalized[SETTING_SPEAKER_IDENTITY]
            )
            if embedding_json is not None:
                await write_setting(connection, SETTING_SPEAKER_VOICE_EMBEDDING, embedding_json)
            await connection.commit()
        finally:
            await connection.close()
        return {
            "display_name": normalized[SETTING_SPEAKER_IDENTITY],
            "voice_enrolled": embedding_json is not None,
        }


async def dispatch_speaker_command(
    command: Envelope, gateway: SpeakerEnrollCommandGateway | None, send: SendFn
) -> None:
    if gateway is None:
        await send(_speaker_error_reply(command.id, "speaker enrollment is not available"))
        return
    try:
        payload = SpeakerEnrollCommandPayload.model_validate(command.payload)
    except ValidationError:
        await send(
            error_reply(
                command.id,
                ProtocolErrorCode.INVALID_PAYLOAD,
                "speaker.enroll payload failed validation",
            )
        )
        return
    try:
        result = await gateway.enroll(payload.display_name, payload.audio_wav_base64)
    except ValueError as exc:
        await send(_speaker_error_reply(command.id, str(exc)))
        return
    except Exception:
        logger.exception("speaker.enroll failed")
        await send(_speaker_error_reply(command.id, "could not save your speaker profile"))
        return
    await send(_ok_reply(command.id, result))
