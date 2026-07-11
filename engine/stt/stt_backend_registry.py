"""Settings-driven STT backend factory."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from engine.stt.openai_compatible_stt import OpenAiCompatibleSttBackend
from engine.stt.parakeet_stt_backend import ParakeetSttBackend
from engine.stt.stt_backend_protocol import SttBackend
from engine.stt.whisper_stt_backend import WhisperSttBackend

STT_ENGINES: frozenset[str] = frozenset({"parakeet", "whisper", "openai_compatible"})
DEFAULT_STT_ENGINE = "parakeet"


def normalize_stt_engine(engine: str | None) -> str:
    if engine in STT_ENGINES:
        return engine
    return DEFAULT_STT_ENGINE


def create_stt_backend(
    engine: str | None,
    *,
    models_dir: Path | None = None,
    model_id: str | None = None,
    openai_base_url: str | None = None,
    openai_api_key: str | Callable[[], str] | None = None,
) -> SttBackend:
    selected = normalize_stt_engine(engine)
    if selected == "whisper":
        from engine.stt.whisper_model_catalog import DEFAULT_WHISPER_MODEL_ID

        return WhisperSttBackend(
            models_dir=models_dir, model_id=model_id or DEFAULT_WHISPER_MODEL_ID
        )
    if selected == "openai_compatible":
        if not openai_base_url or openai_api_key is None:
            raise ValueError("openai_compatible STT requires endpoint and API key")
        return OpenAiCompatibleSttBackend(
            base_url=openai_base_url,
            api_key=openai_api_key,
            model_id=model_id or "whisper-1",
        )
    return ParakeetSttBackend(models_dir=models_dir)
