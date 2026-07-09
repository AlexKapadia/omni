"""STT accuracy tier presets."""

from engine.stt.stt_tier_presets import settings_for_tier, tier_from_settings


def test_tier_from_settings_defaults_to_fast() -> None:
    assert tier_from_settings("parakeet", "") == "fast"


def test_tier_from_settings_whisper_is_enhanced() -> None:
    assert tier_from_settings("whisper", "large-v3") == "enhanced"


def test_tier_from_settings_cloud() -> None:
    assert tier_from_settings("openai_compatible", "whisper-1") == "cloud"


def test_settings_for_enhanced_tier() -> None:
    assert settings_for_tier("enhanced") == {
        "stt_engine": "whisper",
        "stt_model_id": "large-v3",
    }
