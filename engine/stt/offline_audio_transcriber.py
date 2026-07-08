"""Offline audio transcription — decode media/WAV and run Parakeet windows."""

from __future__ import annotations

import subprocess
import uuid
import wave
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import numpy.typing as npt

from engine.audio.audio_frame_types import PIPELINE_SAMPLE_RATE
from engine.stt.parakeet_nemo_transcriber import ParakeetNemoTranscriber

_WINDOW_SAMPLES = PIPELINE_SAMPLE_RATE * 30
_HOP_SAMPLES = PIPELINE_SAMPLE_RATE * 25
_MIN_WINDOW_SAMPLES = PIPELINE_SAMPLE_RATE // 2


@dataclass(frozen=True)
class OfflineSegment:
    stream: str
    text: str
    t_start: float
    t_end: float


def decode_media_to_mono_16k(media_path: Path) -> npt.NDArray[np.float32]:
    """Decode any ffmpeg-supported file to 16 kHz mono float32 samples."""
    result = subprocess.run(
        [
            "ffmpeg",
            "-nostdin",
            "-i",
            str(media_path),
            "-f",
            "s16le",
            "-acodec",
            "pcm_s16le",
            "-ac",
            "1",
            "-ar",
            str(PIPELINE_SAMPLE_RATE),
            "-",
        ],
        capture_output=True,
        check=False,
        timeout=600,
    )
    if result.returncode != 0:
        detail = (result.stderr or b"").decode("utf-8", errors="replace")[-400:]
        raise ValueError(f"ffmpeg could not decode {media_path.name}: {detail}")
    if not result.stdout:
        raise ValueError(f"no audio in {media_path.name}")
    pcm = np.frombuffer(result.stdout, dtype="<i2")
    return (pcm.astype(np.float32) / 32768.0).astype(np.float32, copy=False)


def decode_wav_to_mono_16k(wav_path: Path) -> npt.NDArray[np.float32]:
    """Read a mono 16-bit WAV file into float32 samples (resampled if needed)."""
    with wave.open(str(wav_path), "rb") as reader:
        channels = reader.getnchannels()
        sample_width = reader.getsampwidth()
        rate = reader.getframerate()
        frames = reader.readframes(reader.getnframes())
    if sample_width != 2:
        raise ValueError(f"unsupported WAV sample width in {wav_path.name}")
    pcm = np.frombuffer(frames, dtype="<i2")
    if channels > 1:
        pcm = pcm.reshape(-1, channels)[:, 0]
    samples = pcm.astype(np.float32) / 32768.0
    if rate != PIPELINE_SAMPLE_RATE:
        import soxr

        samples = soxr.resample(samples, rate, PIPELINE_SAMPLE_RATE).astype(np.float32)
    return samples


def transcribe_samples(
    transcriber: ParakeetNemoTranscriber,
    samples: npt.NDArray[np.float32],
    *,
    stream: str = "them",
) -> list[OfflineSegment]:
    """Slide fixed windows over audio and persistable segment rows."""
    if not transcriber.is_loaded:
        transcriber.load()
    segments: list[OfflineSegment] = []
    offset = 0
    while offset < samples.size:
        window = samples[offset : offset + _WINDOW_SAMPLES]
        if window.size < _MIN_WINDOW_SAMPLES:
            break
        words = transcriber.transcribe_window(window)
        if words:
            text = " ".join(w.text for w in words)
            t_start = offset / PIPELINE_SAMPLE_RATE + words[0].t_start
            t_end = offset / PIPELINE_SAMPLE_RATE + words[-1].t_end
            segments.append(OfflineSegment(stream=stream, text=text, t_start=t_start, t_end=t_end))
        offset += _HOP_SAMPLES
    return segments


def load_transcriber(models_dir: Path | None = None) -> ParakeetNemoTranscriber:
    from engine.stt.model_weights_downloader import PARAKEET_FILENAME, models_directory
    from engine.stt.parakeet_nemo_transcriber import stt_dependencies_available

    if not stt_dependencies_available():
        raise ValueError("STT dependencies not installed (uv sync --extra stt)")
    base = models_dir if models_dir is not None else models_directory()
    transcriber = ParakeetNemoTranscriber(base / PARAKEET_FILENAME)
    if not transcriber.is_loaded:
        transcriber.load()
    return transcriber


def new_segment_id() -> str:
    return str(uuid.uuid4())
