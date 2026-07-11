"""STT model loading for live capture: VAD + selected engine, fail closed.

Purpose: owns the heavy STT model lifecycle — Silero VAD plus the selected
live transcriber (Parakeet, Whisper, or openai_compatible), loaded off the
event loop with honest readiness for the heartbeat.
Pipeline position: owned by ``engine.stt.live_capture_service``.

Security / fidelity invariants:
- Fail closed: missing model file or missing STT dependency raises
  ``CaptureServiceError`` — capture cannot start half-ready.
- ``is_ready`` is heartbeat truth: True only once weights are loaded.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from pathlib import Path

import numpy as np
import numpy.typing as npt

from engine.stt.live_transcriber_factory import LiveTranscriber, build_live_transcriber
from engine.stt.model_weights_downloader import SILERO_VAD_FILENAME, models_directory
from engine.stt.silero_onnx_voice_activity_detector import SileroOnnxVoiceActivityDetector
from engine.stt.stt_runtime_status import detect_inference_device, update_stt_runtime_status

VadFactory = Callable[[], Callable[[npt.NDArray[np.float32]], float]]

# Re-export for live_capture_service / tests that import from this module.
__all__ = [
    "CaptureModelLoader",
    "CaptureServiceError",
    "LiveTranscriber",
    "VadFactory",
]


class CaptureServiceError(Exception):
    """User-visible capture failures (already running, models missing...)."""


class CaptureModelLoader:
    """Idempotent, lock-guarded loader for the capture session's STT models."""

    def __init__(
        self,
        models_dir: Path | None = None,
        transcriber: LiveTranscriber | None = None,
        vad_factory: VadFactory | None = None,
        *,
        stt_engine: str = "parakeet",
        stt_model_id: str = "",
        openai_base_url: str = "",
        openai_api_key: str | Callable[[], str] | None = None,
    ) -> None:
        self._models_dir = models_dir if models_dir is not None else models_directory()
        self.transcriber = transcriber
        self.vad_factory = vad_factory
        self._stt_engine = stt_engine
        self._stt_model_id = stt_model_id
        self._openai_base_url = openai_base_url
        self._openai_api_key = openai_api_key
        self._injected_transcriber = transcriber is not None
        self._ready = False
        self._lock = asyncio.Lock()
        self._loaded_key: tuple[str, str, str] | None = None

    def configure(
        self,
        stt_engine: str,
        stt_model_id: str,
        *,
        openai_base_url: str = "",
        openai_api_key: str | Callable[[], str] | None = None,
    ) -> None:
        """Select engine/model before load; invalidates readiness on change."""
        engine = stt_engine.strip() or "parakeet"
        model_id = stt_model_id.strip()
        url = openai_base_url.strip()
        key = (engine, model_id, url)
        if key == (self._stt_engine, self._stt_model_id, self._openai_base_url) and self._ready:
            return
        self._stt_engine = engine
        self._stt_model_id = model_id
        self._openai_base_url = url
        self._openai_api_key = openai_api_key
        if not self._injected_transcriber:
            self.transcriber = None
            self._ready = False
            self._loaded_key = None

    @property
    def is_ready(self) -> bool:
        return self._ready

    async def ensure_loaded(self) -> None:
        """Load VAD + selected STT once; fail closed on missing deps/files."""
        async with self._lock:
            key = (self._stt_engine, self._stt_model_id, self._openai_base_url)
            if self._ready and self._loaded_key == key:
                return
            if self.vad_factory is None:
                vad_model = self._models_dir / SILERO_VAD_FILENAME
                if not vad_model.is_file():
                    raise CaptureServiceError(f"VAD model missing: {vad_model}")
                self.vad_factory = lambda: SileroOnnxVoiceActivityDetector(vad_model)
            if self.transcriber is None:
                self.transcriber = self._build_transcriber()
            if not self.transcriber.is_loaded:
                await asyncio.to_thread(self.transcriber.load)
            device = (
                "cloud" if self._stt_engine == "openai_compatible" else detect_inference_device()
            )
            update_stt_runtime_status(
                engine=self._stt_engine,
                model_id=self._status_model_id(),
                device=device,
            )
            self._loaded_key = key
            self._ready = True

    def _status_model_id(self) -> str:
        if self._stt_engine == "whisper":
            return self._stt_model_id or "large-v3-turbo"
        if self._stt_engine == "openai_compatible":
            return self._stt_model_id or "whisper-1"
        return self._stt_model_id or "parakeet-tdt-0.6b-v2"

    def _build_transcriber(self) -> LiveTranscriber:
        try:
            return build_live_transcriber(
                self._stt_engine,
                models_dir=self._models_dir,
                model_id=self._stt_model_id,
                openai_base_url=self._openai_base_url or None,
                openai_api_key=self._openai_api_key,
            )
        except ValueError as exc:
            raise CaptureServiceError(str(exc)) from exc
