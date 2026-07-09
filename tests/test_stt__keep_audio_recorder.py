"""keep-audio: raw-audio retention, ON by default, saved as MP3.

Adversarial coverage of the retention binding: with no setting (or the setting
unset) a recorder IS created — recordings are kept by default — while an
explicit ``False`` opts out. When enabled, a session writes real, playable
16 kHz mono 16-bit WAV, then on close transcodes each stream to MP3 and removes
the WAV; a failed/absent encoder keeps the WAV (fail-soft), and a corrupt frame
disables retention without raising into live capture.
"""

import shutil
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


async def test_recorder_created_by_default(tmp_path: Path, real_migrations_dir: Path) -> None:
    connection = await _connection(tmp_path, real_migrations_dir)
    try:
        recorder = await create_keep_audio_recorder_if_enabled(connection, "meeting-1")
    finally:
        await connection.close()
    # Retention is ON by default: no setting => recordings are kept.
    assert recorder is not None


async def test_recorder_is_none_when_setting_false(
    tmp_path: Path, real_migrations_dir: Path
) -> None:
    connection = await _connection(tmp_path, real_migrations_dir)
    try:
        await write_setting(connection, SETTING_KEEP_AUDIO, False)  # explicit opt-out
        recorder = await create_keep_audio_recorder_if_enabled(connection, "meeting-1")
    finally:
        await connection.close()
    assert recorder is None


async def test_recorder_writes_valid_wav_before_encode(
    tmp_path: Path, real_migrations_dir: Path
) -> None:
    # A no-op encoder isolates the WAV-writing behaviour from ffmpeg: the WAV
    # must be well-formed 16 kHz mono 16-bit PCM with the exact frame count.
    audio_dir = tmp_path / "audio"
    connection = await _connection(tmp_path, real_migrations_dir)
    try:
        recorder = await create_keep_audio_recorder_if_enabled(
            connection, "meeting-42", audio_dir=audio_dir
        )
    finally:
        await connection.close()
    assert recorder is not None
    recorder._encoder = lambda _wav: None  # keep the WAV so we can inspect it
    recorder.write_frame(_frame(StreamLabel.ME, n=160))
    recorder.write_frame(_frame(StreamLabel.ME, n=160))
    recorder.write_frame(_frame(StreamLabel.THEM, n=80))
    recorder.close()

    me_wav = audio_dir / "meeting-42" / "me.wav"
    with wave.open(str(me_wav), "rb") as handle:
        assert handle.getnchannels() == 1
        assert handle.getsampwidth() == 2  # 16-bit PCM
        assert handle.getframerate() == PIPELINE_SAMPLE_RATE
        assert handle.getnframes() == 320  # two 160-sample frames concatenated


def test_close_transcodes_to_mp3_and_removes_wav(tmp_path: Path) -> None:
    # A fake encoder proves the close() contract WITHOUT ffmpeg: it is handed
    # the finalised WAV, produces the sibling .mp3, and the WAV is then removed.
    def _fake_encode(wav_path: Path) -> Path:
        mp3_path = wav_path.with_suffix(".mp3")
        mp3_path.write_bytes(b"ID3fake-mp3")
        return mp3_path

    recorder = KeepAudioRecorder(tmp_path / "session", encoder=_fake_encode)
    recorder.write_frame(_frame(StreamLabel.ME, n=64))
    recorder.close()

    session = tmp_path / "session"
    assert (session / "me.mp3").is_file()  # MP3 is the retained copy
    assert not (session / "me.wav").exists()  # WAV removed after transcode


def test_close_keeps_wav_when_encoder_unavailable(tmp_path: Path) -> None:
    # Fail-soft: encoder returns None (e.g. ffmpeg missing) => the WAV survives
    # as the kept audio; a format problem must never lose the recording.
    recorder = KeepAudioRecorder(tmp_path / "session", encoder=lambda _wav: None)
    recorder.write_frame(_frame(StreamLabel.ME, n=64))
    recorder.close()

    session = tmp_path / "session"
    assert (session / "me.wav").is_file()  # WAV kept
    assert not (session / "me.mp3").exists()


def test_close_keeps_wav_when_encoder_raises(tmp_path: Path) -> None:
    # An encoder that raises must not escape close() nor lose the WAV.
    def _boom(_wav: Path) -> Path:
        raise RuntimeError("ffmpeg exploded")

    recorder = KeepAudioRecorder(tmp_path / "session", encoder=_boom)
    recorder.write_frame(_frame(StreamLabel.ME, n=64))
    recorder.close()  # must not raise
    assert (tmp_path / "session" / "me.wav").is_file()


def test_unwritable_target_disables_retention_fail_soft(tmp_path: Path) -> None:
    # A FILE where the session directory should be: mkdir fails on the first
    # frame. Retention must disable itself, never raise into the drain loop
    # (a live capture is never taken down by a retention error).
    blocker = tmp_path / "blocked"
    blocker.write_text("i am a file, not a directory", encoding="utf-8")
    recorder = KeepAudioRecorder(blocker / "session")  # under a file: unmakeable
    recorder.write_frame(_frame(StreamLabel.ME, n=32))  # must not raise
    assert recorder._disabled is True


def test_close_produces_real_playable_mp3_with_ffmpeg(tmp_path: Path) -> None:
    # Integration: with the REAL ffmpeg encoder, close() must yield a genuine
    # MP3 (non-empty, WAV removed) proving the end-to-end retention format.
    if shutil.which("ffmpeg") is None:  # environment gate, not a behaviour skip
        import pytest

        pytest.skip("ffmpeg not installed on this host")

    recorder = KeepAudioRecorder(tmp_path / "session")  # real encode_wav_to_mp3
    for _ in range(20):  # ~a few hundred ms of audio so lame emits frames
        recorder.write_frame(_frame(StreamLabel.ME, n=160))
    recorder.close()

    mp3_path = tmp_path / "session" / "me.mp3"
    assert mp3_path.is_file()
    assert mp3_path.stat().st_size > 0
    assert not (tmp_path / "session" / "me.wav").exists()
