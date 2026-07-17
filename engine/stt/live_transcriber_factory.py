"""Build a live-capture / dictation transcriber from STT engine settings.

Purpose: single factory for Parakeet, Whisper, and openai_compatible so live
capture and dictation cannot drift (cloud STT must not fall through to
Parakeet). Raises ``ValueError`` on missing deps/key/URL — callers wrap into
their domain error.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Protocol

import numpy as np
import numpy.typing as npt

from engine.stt.parakeet_nemo_transcriber import (
    ParakeetNemoTranscriber,
    stt_dependencies_available,
)
from engine.stt.stt_backend_registry import normalize_stt_engine
from engine.stt.word_token_types import WordToken


class LiveTranscriber(Protocol):
    """Minimal surface live capture / dictation need from any STT engine."""

    @property
    def is_loaded(self) -> bool: ...

    def load(self) -> None: ...

    def transcribe_window(self, samples: npt.NDArray[np.float32]) -> list[WordToken]: ...


def build_live_transcriber(
    engine: str,
    *,
    models_dir: Path,
    model_id: str = "",
    openai_base_url: str | None = None,
    openai_api_key: str | Callable[[], str] | None = None,
) -> LiveTranscriber:
    """Construct the selected live STT backend; fail closed via ValueError."""
    selected = normalize_stt_engine(engine)
    if selected == "whisper":
        from engine.stt.whisper_model_catalog import (
            DEFAULT_WHISPER_MODEL_ID,
            is_whisper_model_present,
        )
        from engine.stt.whisper_stt_backend import WhisperSttBackend

        mid = model_id or DEFAULT_WHISPER_MODEL_ID
        if not is_whisper_model_present(models_dir, mid):
            raise ValueError(
                f"Whisper model {mid!r} is not installed — "
                "download it in Settings → Transcription"
            )
        try:
            import pywhispercpp  # noqa: F401
        except ImportError as exc:
            raise ValueError(
                "Whisper live capture requires pywhispercpp (uv sync --extra whisper)"
            ) from exc
        return WhisperSttBackend(models_dir=models_dir, model_id=mid)

    if selected == "openai_compatible":
        from engine.stt.openai_compatible_stt import OpenAiCompatibleSttBackend

        if not openai_base_url or openai_api_key is None:
            raise ValueError("openai_compatible STT requires endpoint and API key")
        return OpenAiCompatibleSttBackend(
            base_url=openai_base_url,
            api_key=openai_api_key,
            model_id=model_id or "whisper-1",
        )

    if not stt_dependencies_available():
        raise ValueError("STT dependencies not installed (uv sync --extra stt)")
    from engine.stt.model_weights_downloader import PARAKEET_FILENAME

    return ParakeetNemoTranscriber(models_dir / PARAKEET_FILENAME)
