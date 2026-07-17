"""Load STT backend from persisted app settings."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import aiosqlite

from engine.security.provider_key_store import ProviderKeyStore
from engine.storage.app_settings_repository import (
    SETTING_STT_ENGINE,
    SETTING_STT_MODEL_ID,
    SETTING_STT_OPENAI_BASE_URL,
    read_setting,
)
from engine.stt.stt_backend_protocol import SttBackend
from engine.stt.stt_backend_registry import create_stt_backend
from engine.stt.stt_runtime_status import detect_inference_device, update_stt_runtime_status


async def load_stt_backend_from_settings(
    connection: aiosqlite.Connection,
    *,
    models_dir: Path | None = None,
) -> SttBackend:
    engine = await read_setting(connection, SETTING_STT_ENGINE)
    model_id = await read_setting(connection, SETTING_STT_MODEL_ID)
    base_url = await read_setting(connection, SETTING_STT_OPENAI_BASE_URL)
    engine_str = engine if isinstance(engine, str) else "parakeet"
    model_str = model_id.strip() if isinstance(model_id, str) else ""
    url_str = base_url.strip() if isinstance(base_url, str) else ""
    api_key: Callable[[], str] | None = None
    if engine_str == "openai_compatible":
        key_store = ProviderKeyStore()

        def reveal_openai_key() -> str:
            stored = key_store.get_key("openai")
            if stored is None:
                raise ValueError("OpenAI API key required for cloud STT")
            return stored.reveal()

        api_key = reveal_openai_key
    backend = create_stt_backend(
        engine_str,
        models_dir=models_dir,
        model_id=model_str or None,
        openai_base_url=url_str or None,
        openai_api_key=api_key,
    )
    device = "cloud" if engine_str == "openai_compatible" else detect_inference_device()
    update_stt_runtime_status(engine=engine_str, model_id=model_str, device=device)
    return backend
