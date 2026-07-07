"""M7 keep-audio: opt-in raw-audio retention, OFF by default.

Adversarial coverage of the audio-discard binding: with no setting (or the
setting False) NO recorder is created — audio is discarded after
transcription. Only when ``keep_audio`` is persisted True does a session
write real, playable 16 kHz mono 16-bit WAV files; and a corrupt frame
disables retention fail-soft without raising into live capture.
"""

import wave
from pathlib import Path

import numpy as np

from engine.audio.audio_frame_types import PIPELINE_SAMPLE_RATE, AudioFrame, StreamLabel
from engine.storage.app_settings_repository import SETTING_KEEP_AUDIO, write_setting
from engine.storage.sqlite_connection import open_sqlite_connection
from engine.storage.sqlite_migrations_runner import apply_migrations
from engine.stt.keep_audio_recorder import (
    KeepAudioRecorder,
    create_keep_audio_recorder_if_enabled,
)


def _frame(stream: StreamLabel, n: int = 320) -> AudioFrame:
    # A short ramp in [-1, 1] so int16 conversion is exercised across the range.
    samples = np.linspace(-1.0, 1.0, num=n, dtype=np.float32)
    return AudioFrame(stream=stream, samples=samples, t_start_monotonic=0.0)


async def _connection(tmp_path: Path, real_migrations_dir: Path):  # type: ignore[no-untyped-def]
    db = tmp_path / "omni.db"
    await apply_migrations(db, real_migrations_dir)
    return await open_sqlite_connection(db)


async def test_recorder_is_none_by_default(tmp_path: Path, real_migrations_dir: Path) -> None:
    connection = await _connection(tmp_path, real_migrations_dir)
    try:
        recorder = await create_keep_audio_recorder_if_enabled(connection, "meeting-1")
    finally:
        await connection.close()
    # Deny by default: no setting => no retention (audio discarded).
    assert recorder is None


async def test_recorder_is_none_when_setting_false(
    tmp_path: Path, real_migrations_dir: Path
) -> None:
    connection = await _connection(tmp_path, real_migrations_dir)
    try:
        await write_setting(connection, SETTING_KEEP_AUDIO, False)
        recorder = await create_keep_audio_recorder_if_enabled(connection, "meeting-1")
    finally:
        await connection.close()
    assert recorder is None


async def test_recorder_created_and_writes_valid_wav_when_enabled(
    tmp_path: Path, real_migrations_dir: Path
) -> None:
    audio_dir = tmp_path / "audio"
    connection = await _connection(tmp_path, real_migrations_dir)
    try:
        await write_setting(connection, SETTING_KEEP_AUDIO, True)  # explicit opt-in
        recorder = await create_keep_audio_recorder_if_enabled(
            connection, "meeting-42", audio_dir=audio_dir
        )
    finally:
        await connection.close()
    assert recorder is not None
    recorder.write_frame(_frame(StreamLabel.ME, n=160))
    recorder.write_frame(_frame(StreamLabel.ME, n=160))
    recorder.write_frame(_frame(StreamLabel.THEM, n=80))
    recorder.close()

    me_wav = audio_dir / "meeting-42" / "me.wav"
    them_wav = audio_dir / "meeting-42" / "them.wav"
    assert me_wav.is_file() and them_wav.is_file()
    with wave.open(str(me_wav), "rb") as handle:
        assert handle.getnchannels() == 1
        assert handle.getsampwidth() == 2  # 16-bit PCM
        assert handle.getframerate() == PIPELINE_SAMPLE_RATE
        assert handle.getnframes() == 320  # two 160-sample frames concatenated


def test_unwritable_target_disables_retention_fail_soft(tmp_path: Path) -> None:
    # A FILE where the session directory should be: mkdir fails on the first
    # frame. Retention must disable itself, never raise into the drain loop
    # (a live capture is never taken down by a retention error).
    blocker = tmp_path / "blocked"
    blocker.write_text("i am a file, not a directory", encoding="utf-8")
    recorder = KeepAudioRecorder(blocker / "session")  # under a file: unmakeable
    recorder.write_frame(_frame(StreamLabel.ME, n=32))  # must not raise
    assert recorder._disabled is True
