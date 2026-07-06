"""Parakeet-TDT 0.6B v2 transcriber (NeMo): audio window -> timestamped words.

Purpose: wraps the NVIDIA Parakeet-TDT streaming-window transcription —
loads the ``.nemo`` checkpoint once (CUDA with auto precision, CPU
fallback), then converts 16 kHz mono float32 windows into word tokens
with window-relative timestamps.
Pipeline position: called (via a worker thread) by
``engine.stt.per_stream_transcription_pipeline``; its words feed the
streaming chunk merger.

Precision policy (auto-detected at load):
- CUDA + compute capability >= 8 (Ampere/Ada, e.g. RTX 4070): bfloat16
  autocast — fp32 dynamic range, half the bandwidth.
- Older CUDA: float16 autocast.
- No CUDA, or CUDA out-of-memory at load: CPU float32 (honest fallback,
  logged — never a crash).

FIDELITY INVARIANT (binding user mandate): the model's word strings pass
through VERBATIM — no casing changes, no filler removal, no substitutions.

Security invariants: weights load from the local models directory and
inference is fully local; audio windows are transcribed and released,
never persisted (local-only / discard-after-transcription).

Heavy imports (torch / nemo) are lazy so this module imports cleanly
where the optional ``stt`` extra is absent (e.g. Linux CI).
"""

import logging
import threading
from pathlib import Path
from typing import Any

import numpy as np
import numpy.typing as npt

from engine.stt.word_token_types import WordToken

logger = logging.getLogger(__name__)


def stt_dependencies_available() -> bool:
    """True when the optional heavy STT stack (torch + NeMo) is importable."""
    try:
        import nemo.collections.asr  # noqa: F401
        import torch  # noqa: F401
    except ImportError:
        return False
    return True


class ParakeetNemoTranscriber:
    """Loads Parakeet-TDT once and transcribes windows, GPU-serialised.

    A single instance is shared by BOTH streams; the internal lock
    serialises model calls so the two pipelines never contend for the GPU
    mid-kernel (8 GB card: one 0.6B model, one inference at a time).
    """

    def __init__(self, model_path: Path) -> None:
        self._model_path = model_path
        self._model: Any = None
        self._device = "cpu"
        self._autocast_dtype: Any = None
        # Serialises load + every transcribe call (shared-GPU discipline).
        self._lock = threading.Lock()

    @property
    def is_loaded(self) -> bool:
        return self._model is not None

    def load(self) -> None:
        """Load the checkpoint (idempotent, blocking — call off the loop).

        Fails closed on a missing file; falls back to CPU on CUDA OOM.
        """
        with self._lock:
            if self._model is not None:
                return
            if not self._model_path.is_file():
                raise FileNotFoundError(f"Parakeet model not found: {self._model_path}")
            import torch

            device, dtype = self._detect_device_and_dtype()
            try:
                self._load_onto(device)
            except torch.cuda.OutOfMemoryError:
                # CUDA OOM fallback: CPU is slow but honest; report, don't die.
                logger.warning("CUDA out of memory loading Parakeet; falling back to CPU")
                torch.cuda.empty_cache()
                device, dtype = "cpu", None
                self._load_onto(device)
            self._device = device
            self._autocast_dtype = dtype
            logger.info(
                "Parakeet-TDT loaded on %s (autocast=%s)",
                device,
                getattr(dtype, "__str__", lambda: "off")() if dtype else "off",
            )
            self._warm_up()

    def transcribe_window(self, samples: npt.NDArray[np.float32]) -> list[WordToken]:
        """Transcribe one 16 kHz mono window -> words with window-relative times.

        Thread-safe (lock-serialised). Empty/silent audio yields ``[]``.
        """
        if self._model is None:
            raise RuntimeError("transcriber used before load()")  # Fail closed.
        if samples.size == 0:
            return []
        import torch

        with self._lock, torch.inference_mode():
            if self._device == "cuda" and self._autocast_dtype is not None:
                with torch.autocast(device_type="cuda", dtype=self._autocast_dtype):
                    hypotheses = self._run_model(samples)
            else:
                hypotheses = self._run_model(samples)
        return _words_from_hypotheses(hypotheses)

    def _run_model(self, samples: npt.NDArray[np.float32]) -> Any:
        return self._model.transcribe(
            audio=[samples.astype(np.float32, copy=False)],
            batch_size=1,
            timestamps=True,  # Word timestamps are the merge substrate.
            verbose=False,  # No progress bars into the engine log.
        )

    def _load_onto(self, device: str) -> None:
        import nemo.collections.asr as nemo_asr

        model = nemo_asr.models.ASRModel.restore_from(
            str(self._model_path), map_location=device
        )
        model.eval()
        self._model = model.to(device)

    def _warm_up(self) -> None:
        """One dummy inference so kernel compilation is paid at load time,
        not on the user's first utterance (speed-is-a-showcase mandate)."""
        import torch

        try:
            silence = np.zeros(16_000, dtype=np.float32)  # 1 s of silence.
            with torch.inference_mode():
                self._run_model(silence)
        except Exception:  # Warm-up is an optimisation, never a blocker.
            logger.exception("Parakeet warm-up inference failed (continuing)")

    @staticmethod
    def _detect_device_and_dtype() -> tuple[str, Any]:
        import torch

        if not torch.cuda.is_available():
            return "cpu", None
        major, _minor = torch.cuda.get_device_capability(0)
        # Ampere/Ada (>= 8.x) has native bfloat16 — fp32 range, no overflow
        # risk; older cards get float16.
        return "cuda", (torch.bfloat16 if major >= 8 else torch.float16)


def _words_from_hypotheses(hypotheses: Any) -> list[WordToken]:
    """Extract word tokens from NeMo transcribe() output, verbatim.

    NeMo returns a list of Hypothesis objects whose ``timestamp['word']``
    entries carry ``word`` / ``start`` / ``end`` (seconds). Anything absent
    (silence) yields an empty list rather than an error.
    """
    if not hypotheses:
        return []
    hypothesis = hypotheses[0]
    timestamp = getattr(hypothesis, "timestamp", None) or {}
    words: list[WordToken] = []
    for entry in timestamp.get("word", []):
        words.append(
            WordToken(
                # Verbatim model output — fidelity invariant.
                text=str(entry["word"]),
                t_start=float(entry["start"]),
                t_end=float(entry["end"]),
            )
        )
    return words
