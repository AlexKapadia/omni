"""mic_device_id setting: empty default, `{index}:{name}` format, known key."""

from __future__ import annotations

import pytest

from engine.storage.app_settings_repository import KNOWN_SETTINGS_KEYS
from engine.wiring.app_settings_command_gateway import SETTINGS_DEFAULTS
from engine.wiring.settings_value_validation import SettingsValueError, validate_settings_values

SETTING_MIC_DEVICE_ID = "mic_device_id"


def test_mic_device_id_is_a_known_settings_key() -> None:
    assert SETTING_MIC_DEVICE_ID in KNOWN_SETTINGS_KEYS


def test_mic_device_id_defaults_to_empty_string() -> None:
    assert SETTINGS_DEFAULTS[SETTING_MIC_DEVICE_ID] == ""


def test_mic_device_id_accepts_empty_string() -> None:
    out = validate_settings_values({SETTING_MIC_DEVICE_ID: ""})
    assert out[SETTING_MIC_DEVICE_ID] == ""


def test_mic_device_id_accepts_index_name_format() -> None:
    out = validate_settings_values({SETTING_MIC_DEVICE_ID: "9:USB Mic"})
    assert out[SETTING_MIC_DEVICE_ID] == "9:USB Mic"


def test_mic_device_id_rejects_malformed() -> None:
    with pytest.raises(SettingsValueError):
        validate_settings_values({SETTING_MIC_DEVICE_ID: "USB Mic"})
    with pytest.raises(SettingsValueError):
        validate_settings_values({SETTING_MIC_DEVICE_ID: "9:"})
    with pytest.raises(SettingsValueError):
        validate_settings_values({SETTING_MIC_DEVICE_ID: 9})  # type: ignore[dict-item]
