"""wav_to_mp3_encoder: fail-soft ffmpeg transcode of kept audio to MP3.

Adversarial coverage of the retention-format helper: a missing ffmpeg, a
raised subprocess, and a garbage input all return ``None`` (the caller keeps
the WAV — a format problem never loses audio); a real WAV round-trips to a
genuine, decodable MP3.
"""

import shutil
import subprocess
import wave
from pathlib import Path

import numpy as np
import pytest

from engine.audio import wav_to_mp3_encoder
from engine.audio.audio_frame_types import PIPELINE_SAMPLE_RATE
from engine.audio.wav_to_mp3_encoder import encode_wav_to_mp3

_HAVE_FFMPEG = shutil.which("ffmpeg") is not None


def _write_wav(path: Path, seconds: float = 0.5) -> None:
    n = int(PIPELINE_SAMPLE_RATE * seconds)
    tone = (0.3 * np.sin(np.linspace(0, 220 * 2 * np.pi, n))).astype(np.float32)
    pcm16 = (np.clip(tone, -1.0, 1.0) * 32767).astype("<i2")
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(PIPELINE_SAMPLE_RATE)
        handle.writeframes(pcm16.tobytes())


def test_returns_none_when_ffmpeg_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(wav_to_mp3_encoder.shutil, "which", lambda _name: None)
    wav = tmp_path / "me.wav"
    _write_wav(wav)
    assert encode_wav_to_mp3(wav) is None
    assert not (tmp_path / "me.mp3").exists()  # nothing produced, WAV untouched


def test_returns_none_when_subprocess_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(wav_to_mp3_encoder.shutil, "which", lambda _name: "/usr/bin/ffmpeg")

    def _boom(*_args: object, **_kwargs: object) -> object:
        raise OSError("cannot spawn ffmpeg")

    monkeypatch.setattr(wav_to_mp3_encoder.subprocess, "run", _boom)
    wav = tmp_path / "me.wav"
    _write_wav(wav)
    assert encode_wav_to_mp3(wav) is None  # fail-soft: no raise, WAV kept by caller


def test_returns_none_when_ffmpeg_exits_nonzero(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(wav_to_mp3_encoder.shutil, "which", lambda _name: "/usr/bin/ffmpeg")

    def _fail(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[bytes]:
        return subprocess.CompletedProcess(args=[], returncode=1, stdout=b"", stderr=b"boom")

    monkeypatch.setattr(wav_to_mp3_encoder.subprocess, "run", _fail)
    wav = tmp_path / "me.wav"
    _write_wav(wav)
    assert encode_wav_to_mp3(wav) is None


@pytest.mark.skipif(not _HAVE_FFMPEG, reason="ffmpeg not installed on this host")
def test_encodes_real_wav_to_mp3(tmp_path: Path) -> None:
    wav = tmp_path / "me.wav"
    _write_wav(wav, seconds=0.5)
    mp3 = encode_wav_to_mp3(wav)
    assert mp3 is not None
    assert mp3 == tmp_path / "me.mp3"
    assert mp3.is_file() and mp3.stat().st_size > 0
    # The output must be a genuine, decodable MP3 — ffmpeg can read it back.
    probe = subprocess.run(  # noqa: S603 - fixed local argv, no untrusted input
        ["ffmpeg", "-nostdin", "-v", "error", "-i", str(mp3), "-f", "null", "-"],  # noqa: S607
        capture_output=True,
        check=False,
        timeout=60,
    )
    assert probe.returncode == 0


@pytest.mark.skipif(not _HAVE_FFMPEG, reason="ffmpeg not installed on this host")
def test_returns_none_on_garbage_input(tmp_path: Path) -> None:
    garbage = tmp_path / "me.wav"
    garbage.write_bytes(b"this is not audio at all")  # ffmpeg cannot decode
    assert encode_wav_to_mp3(garbage) is None
