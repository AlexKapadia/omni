"""STT model loading for live capture: VAD + Parakeet readiness, fail closed.

Purpose: the single owner of the heavy STT model lifecycle — locates the
Silero VAD ONNX file, constructs the Parakeet transcriber, loads weights off
the event loop, and reports honest readiness for the heartbeat.
Pipeline position: owned by ``engine.stt.live_capture_service``; sits above
``engine.stt.silero_onnx_voice_activity_detector`` and
``engine.stt.parakeet_nemo_transcriber``.

Security / fidelity invariants:
- Fail closed: a missing model file or missing STT dependency raises a
  clear ``CaptureServiceError`` — capture cannot start half-ready.
- ``is_ready`` is heartbeat truth: True only once weights are actually
  loaded, never claimed early.
"""

import asyncio
from collections.abc import Callable
from pathlib import Path

import numpy as np
import numpy.typing as npt

from engine.stt.model_weights_downloader import SILERO_VAD_FILENAME, models_directory
from engine.stt.parakeet_nemo_transcriber import (
    ParakeetNemoTranscriber,
    stt_dependencies_available,
)
from engine.stt.silero_onnx_voice_activity_detector import SileroOnnxVoiceActivityDetector

# Test seam: production default is the real stateful Silero VAD per stream.
VadFactory = Callable[[], Callable[[npt.NDArray[np.float32]], float]]


class CaptureServiceError(Exception):
    """User-visible capture failures (already running, models missing...)."""


class CaptureModelLoader:
    """Idempotent, lock-guarded loader for the capture session's STT models.

    ``transcriber`` / ``vad_factory`` are injectable test seams; when left
    None the real Parakeet + Silero models are located under ``models_dir``.
    """

    def __init__(
        self,
        models_dir: Path | None = None,
        transcriber: ParakeetNemoTranscriber | None = None,
        vad_factory: VadFactory | None = None,
    ) -> None:
        self._models_dir = models_dir if models_dir is not None else models_directory()
        self.transcriber = transcriber
        self.vad_factory = vad_factory
        self._ready = False
        self._lock = asyncio.Lock()

    @property
    def is_ready(self) -> bool:
        """Heartbeat truth: True only once models are actually loaded."""
        return self._ready

    async def ensure_loaded(self) -> None:
        """Load VAD + Parakeet once; raises ``CaptureServiceError`` with a
        clear reason on any missing file/dependency (fail closed)."""
        async with self._lock:
            if self._ready:
                return
            if self.vad_factory is None:
                vad_model = self._models_dir / SILERO_VAD_FILENAME
                if not vad_model.is_file():
                    raise CaptureServiceError(f"VAD model missing: {vad_model}")
                self.vad_factory = lambda: SileroOnnxVoiceActivityDetector(vad_model)
            if self.transcriber is None:
                if not stt_dependencies_available():
                    raise CaptureServiceError(
                        "STT dependencies not installed (uv sync --extra stt)"
                    )
                from engine.stt.model_weights_downloader import PARAKEET_FILENAME

                self.transcriber = ParakeetNemoTranscriber(self._models_dir / PARAKEET_FILENAME)
            if not self.transcriber.is_loaded:
                # Heavy load off the event loop; heartbeats keep flowing.
                await asyncio.to_thread(self.transcriber.load)
            self._ready = True
