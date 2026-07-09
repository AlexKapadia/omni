"""Accuracy-tier presets mapping to persisted STT settings."""

from __future__ import annotations

from typing import Literal

SttTier = Literal["fast", "enhanced", "cloud"]

TIER_LABELS: dict[SttTier, str] = {
    "fast": "Fast — local Parakeet (GPU when available)",
    "enhanced": "Enhanced — local Whisper large-v3 (GPU when available)",
    "cloud": "Cloud — BYOK OpenAI-compatible STT",
}

TIER_TO_SETTINGS: dict[SttTier, dict[str, str]] = {
    "fast": {"stt_engine": "parakeet", "stt_model_id": ""},
    "enhanced": {"stt_engine": "whisper", "stt_model_id": "large-v3"},
    "cloud": {
        "stt_engine": "openai_compatible",
        "stt_model_id": "whisper-1",
    },
}


def tier_from_settings(engine: str | None, model_id: str | None) -> SttTier:
    engine_str = (engine or "parakeet").strip()
    model_str = (model_id or "").strip().lower()
    if engine_str == "openai_compatible":
        return "cloud"
    if engine_str == "whisper":
        if model_str in {"large-v3", "large", "medium", "medium.en"}:
            return "enhanced"
        return "enhanced"
    return "fast"


def settings_for_tier(tier: SttTier) -> dict[str, str]:
    return dict(TIER_TO_SETTINGS[tier])
