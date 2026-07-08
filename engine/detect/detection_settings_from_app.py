"""Map persisted app_settings into DetectionRuleSettings.

Pipeline: ``app_settings`` -> ``detection_settings_from_app`` ->
``AutoStartRulesEngine.apply_settings``.
"""

from engine.detect.auto_start_rules_engine import DetectionRuleSettings
from engine.detect.detection_signal_types import KNOWN_DETECTION_SOURCES
from engine.storage.app_settings_repository import SETTING_DETECTION_AUTO_START_SOURCES

# User-selectable silence auto-stop presets (seconds). 0 disables.
AUTOSTOP_SILENCE_CHOICES: frozenset[int] = frozenset({0, 30, 60, 120})


def detection_rule_settings_from_effective(
    effective: dict[str, object],
) -> DetectionRuleSettings:
    """Build detection rules from the effective settings map."""
    raw_sources = effective.get(SETTING_DETECTION_AUTO_START_SOURCES)
    auto_start_sources: frozenset[str] = frozenset()
    if isinstance(raw_sources, list):
        auto_start_sources = frozenset(
            source
            for source in raw_sources
            if isinstance(source, str) and source in KNOWN_DETECTION_SOURCES
        )
    return DetectionRuleSettings(auto_start_sources=auto_start_sources)
