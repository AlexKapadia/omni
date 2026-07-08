"""Per-key validation + normalisation for ``settings.update`` values.

Purpose: the ONE place every settings value is checked before it may touch
``app_settings`` — typed, bounded, fail-closed. The gateway validates the
WHOLE batch first and only then persists (all-or-nothing, so a half-applied
update can never exist).
Pipeline position: called by
``engine.wiring.app_settings_command_gateway``; sits above
``engine.storage.app_settings_repository`` (closed key set) and
``engine.enhance.note_templates`` (custom-template bounds).

Security invariants:
- Deny by default: unknown keys, wrong types, out-of-bounds values and
  unknown whitelist intent types are all refused with a plain reason.
- ``vault_dir`` is probed for real writability (write + delete a probe
  file) — a path that cannot take the user's notes is refused, never
  stored (fail closed: no surprise vault locations).
- Boolean settings accept ONLY JSON booleans — no truthiness coercion.
"""

from pathlib import Path

from engine.enhance.note_templates import build_custom_template
from engine.storage.app_settings_repository import (
    KNOWN_SETTINGS_KEYS,
    SETTING_ACTIVE_TEMPLATE,
    SETTING_CUSTOM_TEMPLATES,
    SETTING_DISCLOSURE_REMINDER,
    SETTING_INSTANT_EXECUTE_WHITELIST,
    SETTING_KEEP_AUDIO,
    SETTING_KILL_SWITCH,
    SETTING_ONBOARDING_COMPLETE,
    SETTING_PUSH_TO_TALK_HOTKEY,
    SETTING_VAULT_DIR,
    SETTING_DETECTION_AUTO_START_SOURCES,
    SETTING_AUTOSTOP_SILENCE_S,
    SETTING_LIVE_CAPTIONS_OVERLAY,
)
from engine.detect.detection_settings_from_app import AUTOSTOP_SILENCE_CHOICES
from engine.detect.detection_signal_types import KNOWN_DETECTION_SOURCES

# Companion flag (NOT persisted): "create the vault folder if it is missing".
# Lives beside vault_dir in the same update payload; consumed here.
CREATE_VAULT_DIR_FLAG = "create_vault_dir"

# Intent types eligible for instant execution (mirrors DictationIntentType
# minus 'unknown', which is never actionable — deny by default).
INSTANT_EXECUTABLE_INTENT_TYPES: frozenset[str] = frozenset(
    {"create_event", "upsert_contact", "draft_email", "write_note"}
)

_MAX_HOTKEY_CHARS = 64
_MAX_CUSTOM_TEMPLATES = 20
_MAX_PATH_CHARS = 500


class SettingsValueError(ValueError):
    """One refused key/value pair, with a plain-voice reason."""

    def __init__(self, key: str, reason: str) -> None:
        super().__init__(f"{key}: {reason}")
        self.key = key
        self.reason = reason


def _validate_bool(key: str, value: object) -> bool:
    if not isinstance(value, bool):  # strict: no truthiness coercion
        raise SettingsValueError(key, "value must be true or false")
    return value


def _validate_vault_dir(value: object, create_if_missing: bool) -> str:
    """An absolute, existing (or freshly created), WRITABLE directory."""
    key = SETTING_VAULT_DIR
    if not isinstance(value, str) or not value.strip():
        raise SettingsValueError(key, "value must be a folder path")
    raw = value.strip()
    if len(raw) > _MAX_PATH_CHARS:
        raise SettingsValueError(key, "path is too long")
    path = Path(raw)
    if not path.is_absolute():
        raise SettingsValueError(key, "path must be absolute")
    if not path.is_dir():
        if not create_if_missing:
            raise SettingsValueError(key, "folder does not exist")
        try:
            path.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise SettingsValueError(key, f"could not create the folder: {exc}") from exc
    # Real writability probe — fail closed: a vault Omni cannot write is
    # refused now, not discovered at the first meeting note.
    probe = path / ".omni-write-probe"
    try:
        probe.write_text("probe", encoding="utf-8")
        probe.unlink()
    except OSError as exc:
        raise SettingsValueError(key, f"folder is not writable: {exc}") from exc
    return str(path)


def _validate_hotkey(value: object) -> str:
    key = SETTING_PUSH_TO_TALK_HOTKEY
    if not isinstance(value, str):
        raise SettingsValueError(key, "value must be a key combination string")
    trimmed = value.strip()
    if not 1 <= len(trimmed) <= _MAX_HOTKEY_CHARS:
        raise SettingsValueError(key, "value must be 1-64 characters")
    if any(ord(ch) < 32 for ch in trimmed):
        raise SettingsValueError(key, "control characters are not allowed")
    return trimmed


def _validate_whitelist(value: object) -> list[str]:
    key = SETTING_INSTANT_EXECUTE_WHITELIST
    if not isinstance(value, list):
        raise SettingsValueError(key, "value must be a list of intent types")
    normalized: list[str] = []
    for item in value:
        if not isinstance(item, str) or item not in INSTANT_EXECUTABLE_INTENT_TYPES:
            # Deny by default: an unknown intent type can never be whitelisted.
            raise SettingsValueError(key, f"unknown intent type: {item!r}")
        if item not in normalized:
            normalized.append(item)
    return sorted(normalized)


def _validate_active_template(value: object) -> str:
    key = SETTING_ACTIVE_TEMPLATE
    if not isinstance(value, str) or not value.strip():
        raise SettingsValueError(key, "value must be a template id")
    template_id = value.strip()
    is_snake = template_id.replace("_", "").isalnum() and template_id.lower() == template_id
    if not is_snake or len(template_id) > 64:
        raise SettingsValueError(key, "template ids are lowercase snake_case")
    return template_id


def _validate_custom_templates(value: object) -> list[dict[str, object]]:
    """Each entry must construct a valid NoteTemplate (bounds enforced by
    ``build_custom_template``); the normalised dicts are what gets stored."""
    key = SETTING_CUSTOM_TEMPLATES
    if not isinstance(value, list):
        raise SettingsValueError(key, "value must be a list of templates")
    if len(value) > _MAX_CUSTOM_TEMPLATES:
        raise SettingsValueError(key, f"at most {_MAX_CUSTOM_TEMPLATES} custom templates")
    normalized: list[dict[str, object]] = []
    seen_ids: set[str] = set()
    for entry in value:
        if not isinstance(entry, dict):
            raise SettingsValueError(key, "each template must be an object")
        raw_sections = entry.get("sections")
        if not isinstance(raw_sections, list):
            raise SettingsValueError(key, "each template needs a sections list")
        try:
            sections = [
                (str(s.get("title", "")), str(s.get("guidance", "")))
                for s in raw_sections
                if isinstance(s, dict)
            ]
            if len(sections) != len(raw_sections):
                raise ValueError("every section must be an object")
            template = build_custom_template(
                template_id=str(entry.get("template_id", "")),
                display_name=str(entry.get("display_name", "")),
                sections=sections,
                tone_rules=str(entry.get("tone_rules", "")),
            )
        except ValueError as exc:
            raise SettingsValueError(key, str(exc)) from exc
        if template.template_id in seen_ids:
            raise SettingsValueError(key, f"duplicate template id {template.template_id!r}")
        seen_ids.add(template.template_id)
        normalized.append(
            {
                "template_id": template.template_id,
                "display_name": template.display_name,
                "sections": [
                    {"title": s.title, "guidance": s.guidance} for s in template.sections
                ],
                "tone_rules": template.tone_rules,
            }
        )
    return normalized


def _validate_detection_auto_start_sources(value: object) -> list[str]:
    key = SETTING_DETECTION_AUTO_START_SOURCES
    if not isinstance(value, list):
        raise SettingsValueError(key, "value must be a list of detection sources")
    normalized: list[str] = []
    for item in value:
        if not isinstance(item, str) or item not in KNOWN_DETECTION_SOURCES:
            raise SettingsValueError(key, f"unknown detection source: {item!r}")
        if item not in normalized:
            normalized.append(item)
    return sorted(normalized)


def _validate_autostop_silence_s(value: object) -> int:
    key = SETTING_AUTOSTOP_SILENCE_S
    if not isinstance(value, int) or isinstance(value, bool):
        raise SettingsValueError(key, "value must be an integer number of seconds")
    if value not in AUTOSTOP_SILENCE_CHOICES:
        raise SettingsValueError(key, f"value must be one of {sorted(AUTOSTOP_SILENCE_CHOICES)}")
    return value


def validate_settings_values(values: dict[str, object]) -> dict[str, object]:
    """Validate one ``settings.update`` batch; returns the normalised map.

    Raises :class:`SettingsValueError` on the FIRST refused key — the
    gateway persists nothing when any key fails (all-or-nothing).
    """
    create_vault_dir = values.get(CREATE_VAULT_DIR_FLAG, False)
    if not isinstance(create_vault_dir, bool):
        raise SettingsValueError(CREATE_VAULT_DIR_FLAG, "value must be true or false")
    normalized: dict[str, object] = {}
    for key, value in values.items():
        if key == CREATE_VAULT_DIR_FLAG:
            continue  # companion flag, consumed above — never persisted
        if key not in KNOWN_SETTINGS_KEYS:
            # Deny by default: the closed key set is the contract.
            raise SettingsValueError(key, "unknown settings key")
        if key == SETTING_VAULT_DIR:
            normalized[key] = _validate_vault_dir(value, create_vault_dir)
        elif key == SETTING_PUSH_TO_TALK_HOTKEY:
            normalized[key] = _validate_hotkey(value)
        elif key in (
            SETTING_KEEP_AUDIO,
            SETTING_DISCLOSURE_REMINDER,
            SETTING_KILL_SWITCH,
            SETTING_ONBOARDING_COMPLETE,
            SETTING_LIVE_CAPTIONS_OVERLAY,
        ):
            normalized[key] = _validate_bool(key, value)
        elif key == SETTING_INSTANT_EXECUTE_WHITELIST:
            normalized[key] = _validate_whitelist(value)
        elif key == SETTING_ACTIVE_TEMPLATE:
            normalized[key] = _validate_active_template(value)
        elif key == SETTING_CUSTOM_TEMPLATES:
            normalized[key] = _validate_custom_templates(value)
        elif key == SETTING_DETECTION_AUTO_START_SOURCES:
            normalized[key] = _validate_detection_auto_start_sources(value)
        elif key == SETTING_AUTOSTOP_SILENCE_S:
            normalized[key] = _validate_autostop_silence_s(value)
    if not normalized:
        raise SettingsValueError("values", "no persistable settings in the update")
    return normalized
