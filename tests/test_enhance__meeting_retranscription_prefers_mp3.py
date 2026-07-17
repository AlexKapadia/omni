"""Retranscribe prefers kept MP3 over WAV; decodes each format correctly."""

from __future__ import annotations

import struct
import wave
from pathlib import Path

import numpy as np
import pytest

from engine.audio.audio_frame_types import PIPELINE_SAMPLE_RATE, StreamLabel
from engine.enhance.meeting_retranscription_service import (
    decode_kept_audio,
    resolve_kept_audio_path,
    retranscribe_meeting,
)
from engine.stt.offline_audio_transcriber import OfflineSegment
from tests.enhance_test_support import seed_meeting


def _write_tiny_wav(path: Path, *, frames: int = 160) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as writer:
        writer.setnchannels(1)
        writer.setsampwidth(2)
        writer.setframerate(PIPELINE_SAMPLE_RATE)
        writer.writeframes(struct.pack(f"<{frames}h", *([0] * frames)))


def test_resolve_kept_audio_prefers_mp3_over_wav(tmp_path: Path) -> None:
    session = tmp_path / "m-1"
    session.mkdir()
    (session / "them.wav").write_bytes(b"RIFF")
    (session / "them.mp3").write_bytes(b"ID3")
    assert resolve_kept_audio_path(session, StreamLabel.THEM) == session / "them.mp3"


def test_resolve_kept_audio_falls_back_to_wav(tmp_path: Path) -> None:
    session = tmp_path / "m-1"
    wav = session / "me.wav"
    _write_tiny_wav(wav)
    assert resolve_kept_audio_path(session, StreamLabel.ME) == wav


def test_resolve_kept_audio_missing_returns_none(tmp_path: Path) -> None:
    assert resolve_kept_audio_path(tmp_path / "empty", StreamLabel.THEM) is None


def test_decode_kept_audio_wav_path(tmp_path: Path) -> None:
    wav = tmp_path / "me.wav"
    _write_tiny_wav(wav, frames=320)
    samples = decode_kept_audio(wav)
    assert samples.dtype == np.float32
    assert samples.shape == (320,)


def test_decode_kept_audio_mp3_uses_media_decoder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    mp3 = tmp_path / "them.mp3"
    mp3.write_bytes(b"fake-mp3")
    called: list[Path] = []

    def fake_media(path: Path) -> np.ndarray:
        called.append(path)
        return np.zeros(16, dtype=np.float32)

    monkeypatch.setattr(
        "engine.enhance.meeting_retranscription_service.decode_media_to_mono_16k",
        fake_media,
    )
    samples = decode_kept_audio(mp3)
    assert called == [mp3]
    assert samples.shape == (16,)


@pytest.mark.asyncio
async def test_retranscribe_meeting_uses_mp3_when_wav_gone(
    tmp_path: Path,
    real_migrations_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    meeting_id = "m-retranscribe-mp3"
    db_path = tmp_path / "omni.db"
    await seed_meeting(db_path, real_migrations_dir, meeting_id)

    audio_root = tmp_path / "audio"
    session = audio_root / meeting_id
    session.mkdir(parents=True)
    (session / "them.mp3").write_bytes(b"fake")
    (session / "me.mp3").write_bytes(b"fake")
    # WAV deliberately absent — keep-audio deleted them after MP3 encode.

    monkeypatch.setenv("OMNI_AUDIO_DIR", str(audio_root))
    async def fake_backend(*_a: object, **_k: object) -> object:
        return object()

    monkeypatch.setattr(
        "engine.enhance.meeting_retranscription_service.load_stt_backend_from_settings",
        fake_backend,
    )
    decoded: list[str] = []

    def fake_decode(path: Path) -> np.ndarray:
        decoded.append(path.name)
        return np.zeros(160, dtype=np.float32)

    monkeypatch.setattr(
        "engine.enhance.meeting_retranscription_service.decode_kept_audio",
        fake_decode,
    )

    def fake_transcribe(
        _backend: object, _samples: object, *, stream: str = "them"
    ) -> list[OfflineSegment]:
        return [
            OfflineSegment(stream=stream, text=f"said-{stream}", t_start=0.0, t_end=0.5),
        ]

    monkeypatch.setattr(
        "engine.enhance.meeting_retranscription_service.transcribe_samples_with_backend",
        fake_transcribe,
    )

    await retranscribe_meeting(db_path, real_migrations_dir, meeting_id)
    assert sorted(decoded) == ["me.mp3", "them.mp3"]
