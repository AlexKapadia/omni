"""Detection-related settings validation."""

from __future__ import annotations

import pytest

from engine.detect.detection_signal_types import SOURCE_ZOOM
from engine.storage.app_settings_repository import (
    SETTING_AUTOSTOP_SILENCE_S,
    SETTING_DETECTION_AUTO_START_SOURCES,
)
from engine.wiring.settings_value_validation import SettingsValueError, validate_settings_values


def test_detection_auto_start_sources_accepts_known_sources() -> None:
    applied = validate_settings_values(
        {SETTING_DETECTION_AUTO_START_SOURCES: [SOURCE_ZOOM, "teams"]}
    )
    assert applied[SETTING_DETECTION_AUTO_START_SOURCES] == ["teams", SOURCE_ZOOM]


def test_detection_auto_start_sources_rejects_unknown() -> None:
    with pytest.raises(SettingsValueError) as exc:
        validate_settings_values({SETTING_DETECTION_AUTO_START_SOURCES: ["not_a_source"]})
    assert exc.value.key == SETTING_DETECTION_AUTO_START_SOURCES


def test_autostop_silence_s_accepts_presets() -> None:
    applied = validate_settings_values({SETTING_AUTOSTOP_SILENCE_S: 60})
    assert applied[SETTING_AUTOSTOP_SILENCE_S] == 60


def test_autostop_silence_s_rejects_arbitrary() -> None:
    with pytest.raises(SettingsValueError) as exc:
        validate_settings_values({SETTING_AUTOSTOP_SILENCE_S: 45})
    assert exc.value.key == SETTING_AUTOSTOP_SILENCE_S
