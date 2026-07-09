"""BYOK OpenAI-compatible /v1/audio/transcriptions STT."""

from __future__ import annotations

import io
import wave
from collections.abc import Callable
from pathlib import Path

import httpx
import numpy as np
import numpy.typing as npt

from engine.audio.audio_frame_types import PIPELINE_SAMPLE_RATE
from engine.stt.stt_backend_protocol import SttSegment


class OpenAiCompatibleSttBackend:
    def __init__(
        self,
        *,
        base_url: str,
        api_key: str | Callable[[], str],
        model_id: str,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key_provider = (lambda: api_key) if isinstance(api_key, str) else api_key
        self._model_id = model_id

    def transcribe_samples(
        self,
        samples: npt.NDArray[np.float32],
        *,
        stream: str,
        on_partial: Callable[[str], None] | None = None,
    ) -> list[SttSegment]:
        wav_bytes = _samples_to_wav_bytes(samples)
        text = self._transcribe_wav_bytes(wav_bytes)
        if on_partial is not None:
            on_partial(text)
        duration = max(0.1, samples.size / PIPELINE_SAMPLE_RATE)
        return [SttSegment(text=text, t_start=0.0, t_end=duration, stream=stream)]

    def transcribe_file(self, path: str) -> list[SttSegment]:
        with Path(path).open("rb") as handle:
            data = handle.read()
        text = self._transcribe_wav_bytes(data, filename=Path(path).name)
        return [SttSegment(text=text, t_start=0.0, t_end=1.0, stream="them")]

    def _transcribe_wav_bytes(self, data: bytes, *, filename: str = "audio.wav") -> str:
        url = f"{self._base_url}/audio/transcriptions"
        if not url.endswith("/audio/transcriptions"):
            if self._base_url.endswith("/v1"):
                url = f"{self._base_url}/audio/transcriptions"
            else:
                url = f"{self._base_url}/v1/audio/transcriptions"
        with httpx.Client(timeout=120.0) as client:
            response = client.post(
                url,
                headers={"Authorization": f"Bearer {self._api_key_provider()}"},
                data={"model": self._model_id},
                files={"file": (filename, data, "audio/wav")},
            )
        response.raise_for_status()
        payload = response.json()
        text = payload.get("text") if isinstance(payload, dict) else None
        if not isinstance(text, str) or not text.strip():
            raise ValueError("STT endpoint returned no text")
        return text.strip()


def _samples_to_wav_bytes(samples: npt.NDArray[np.float32]) -> bytes:
    pcm = np.clip(samples, -1.0, 1.0)
    pcm16 = (pcm * 32767.0).astype(np.int16)
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as writer:
        writer.setnchannels(1)
        writer.setsampwidth(2)
        writer.setframerate(PIPELINE_SAMPLE_RATE)
        writer.writeframes(pcm16.tobytes())
    return buffer.getvalue()
