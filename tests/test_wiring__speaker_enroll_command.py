"""Tests for speaker.enroll command gateway."""

import base64
import wave
from io import BytesIO
from pathlib import Path

import numpy as np
import pytest

from engine.protocol import PROTOCOL_VERSION, Envelope, EnvelopeKind
from engine.storage.app_settings_repository import (
    SETTING_SPEAKER_IDENTITY,
    SETTING_SPEAKER_VOICE_EMBEDDING,
    read_setting,
)
from engine.storage.sqlite_connection import open_sqlite_connection
from engine.wiring.speaker_enroll_command_dispatcher import (
    SpeakerEnrollCommandGateway,
    dispatch_speaker_command,
)


def _pcm_wav_base64(seconds: float = 1.0) -> str:
    samples = (np.sin(np.linspace(0, 20, int(16_000 * seconds))) * 0.5 * 32767).astype(
        np.int16
    )
    buf = BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(16_000)
        wf.writeframes(samples.tobytes())
    return base64.b64encode(buf.getvalue()).decode("ascii")


def _envelope(payload: dict[str, object]) -> Envelope:
    return Envelope(
        v=PROTOCOL_VERSION,
        kind=EnvelopeKind.COMMAND,
        name="speaker.enroll",
        id="sp-1",
        payload=payload,
    )


@pytest.mark.asyncio
async def test_speaker_enroll_saves_name_only(tmp_db_path: Path, real_migrations_dir: Path) -> None:
    gateway = SpeakerEnrollCommandGateway(
        db_path=tmp_db_path, migrations_dir=real_migrations_dir
    )
    sent: list[Envelope] = []

    async def send(env: Envelope) -> None:
        sent.append(env)

    await dispatch_speaker_command(
        _envelope({"display_name": "Alex"}), gateway, send
    )
    assert sent[-1].name == "ok"
    assert sent[-1].payload["display_name"] == "Alex"
    assert sent[-1].payload["voice_enrolled"] is False

    connection = await open_sqlite_connection(tmp_db_path)
    try:
        identity = await read_setting(connection, SETTING_SPEAKER_IDENTITY)
        embedding = await read_setting(connection, SETTING_SPEAKER_VOICE_EMBEDDING)
    finally:
        await connection.close()
    assert identity == "Alex"
    assert embedding in ("", None)


@pytest.mark.asyncio
async def test_speaker_enroll_with_voice_sets_embedding(
    tmp_db_path: Path, real_migrations_dir: Path
) -> None:
    gateway = SpeakerEnrollCommandGateway(
        db_path=tmp_db_path, migrations_dir=real_migrations_dir
    )
    sent: list[Envelope] = []

    async def send(env: Envelope) -> None:
        sent.append(env)

    await dispatch_speaker_command(
        _envelope({"display_name": "Alex", "audio_wav_base64": _pcm_wav_base64()}),
        gateway,
        send,
    )
    assert sent[-1].payload["voice_enrolled"] is True

    connection = await open_sqlite_connection(tmp_db_path)
    try:
        embedding = await read_setting(connection, SETTING_SPEAKER_VOICE_EMBEDDING)
    finally:
        await connection.close()
    assert isinstance(embedding, str)
    assert len(embedding) > 10


@pytest.mark.asyncio
async def test_speaker_enroll_rejects_empty_name(
    tmp_db_path: Path, real_migrations_dir: Path
) -> None:
    gateway = SpeakerEnrollCommandGateway(
        db_path=tmp_db_path, migrations_dir=real_migrations_dir
    )
    sent: list[Envelope] = []

    async def send(env: Envelope) -> None:
        sent.append(env)

    await dispatch_speaker_command(
        _envelope({"display_name": "   "}), gateway, send
    )
    assert sent[-1].name == "error"
