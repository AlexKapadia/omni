"""Repository for ``app_settings`` rows: the engine-side settings table.

Purpose: the ONLY place app settings are read or written. Settings are
key -> JSON value pairs (migration 0009); every write also lands in the
append-only ``app_settings_history`` trail via schema triggers, so a
setting can never change without leaving a row.
Pipeline position: written by the M7 settings command gateway
(``engine.wiring.app_settings_command_gateway``); read at their point of
use by capture (keep-audio), finalization (custom templates), and the
instant-execute whitelist check.

Security invariants:
- KNOWN_SETTINGS_KEYS is the closed set of legal keys — an unknown key is
  refused with ``UnknownSettingsKeyError`` (deny by default), never stored.
- Values are stored as exact JSON text (booleans/lists round-trip exactly;
  no float coercion of anything numeric-looking).
- All SQL is parameterised (injection defence).
"""

import json
from datetime import UTC, datetime

import aiosqlite

# The closed set of settings the engine understands. Adding a key here is a
# deliberate, reviewed change — settings.update refuses everything else.
SETTING_VAULT_DIR = "vault_dir"
SETTING_PUSH_TO_TALK_HOTKEY = "push_to_talk_hotkey"
SETTING_KEEP_AUDIO = "keep_audio"
SETTING_DISCLOSURE_REMINDER = "disclosure_reminder"
SETTING_KILL_SWITCH = "kill_switch"
SETTING_INSTANT_EXECUTE_WHITELIST = "instant_execute_whitelist"
SETTING_ACTIVE_TEMPLATE = "active_template"
SETTING_CUSTOM_TEMPLATES = "custom_templates"
SETTING_ONBOARDING_COMPLETE = "onboarding_complete"
SETTING_DETECTION_AUTO_START_SOURCES = "detection_auto_start_sources"
SETTING_AUTOSTOP_SILENCE_S = "autostop_silence_s"
SETTING_LIVE_CAPTIONS_OVERLAY = "live_captions_overlay"
SETTING_AEC_ENABLED = "aec_enabled"
SETTING_LIVE_TRANSLATION_LANG = "live_translation_lang"

KNOWN_SETTINGS_KEYS: frozenset[str] = frozenset(
    {
        SETTING_VAULT_DIR,
        SETTING_PUSH_TO_TALK_HOTKEY,
        SETTING_KEEP_AUDIO,
        SETTING_DISCLOSURE_REMINDER,
        SETTING_KILL_SWITCH,
        SETTING_INSTANT_EXECUTE_WHITELIST,
        SETTING_ACTIVE_TEMPLATE,
        SETTING_CUSTOM_TEMPLATES,
        SETTING_ONBOARDING_COMPLETE,
        SETTING_DETECTION_AUTO_START_SOURCES,
        SETTING_AUTOSTOP_SILENCE_S,
        SETTING_LIVE_CAPTIONS_OVERLAY,
        SETTING_AEC_ENABLED,
        SETTING_LIVE_TRANSLATION_LANG,
    }
)


class UnknownSettingsKeyError(ValueError):
    """Raised when a key outside KNOWN_SETTINGS_KEYS is read or written."""

    def __init__(self, key: str) -> None:
        super().__init__(f"unknown settings key: {key!r}")
        self.key = key


def _require_known_key(key: str) -> None:
    """Deny by default: only the closed key set may touch the table."""
    if key not in KNOWN_SETTINGS_KEYS:
        raise UnknownSettingsKeyError(key)


def _utc_now_iso() -> str:
    return datetime.now(tz=UTC).isoformat()


async def read_setting(connection: aiosqlite.Connection, key: str) -> object | None:
    """The decoded JSON value for ``key``, or ``None`` when unset."""
    _require_known_key(key)
    cursor = await connection.execute(
        "SELECT value_json FROM app_settings WHERE key = ?", (key,)
    )
    row = await cursor.fetchone()
    await cursor.close()
    if row is None:
        return None
    # json.loads is typed Any; pin it to object so callers get the strict
    # `object | None` contract (they type-narrow before use).
    decoded: object = json.loads(str(row[0]))
    return decoded


async def read_setting_bool(
    connection: aiosqlite.Connection, key: str, default: bool
) -> bool:
    """A boolean setting; anything not exactly a JSON boolean is the default.

    Strictness is the security posture: a corrupted/wrong-typed value must
    fall back to the (safe) default, never be truthiness-coerced.
    """
    value = await read_setting(connection, key)
    return value if isinstance(value, bool) else default


async def write_setting(connection: aiosqlite.Connection, key: str, value: object) -> None:
    """Upsert one setting (history row appended by the 0009 triggers)."""
    _require_known_key(key)
    await connection.execute(
        "INSERT INTO app_settings (key, value_json, updated_at) VALUES (?, ?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value_json = excluded.value_json, "
        "updated_at = excluded.updated_at",
        (key, json.dumps(value, ensure_ascii=False), _utc_now_iso()),
    )


async def read_all_settings(connection: aiosqlite.Connection) -> dict[str, object]:
    """Every stored setting, decoded. Unknown keys (from a future/older
    schema) are skipped rather than surfaced — deny by default."""
    cursor = await connection.execute("SELECT key, value_json FROM app_settings")
    rows = await cursor.fetchall()
    await cursor.close()
    decoded: dict[str, object] = {}
    for key, value_json in rows:
        if str(key) in KNOWN_SETTINGS_KEYS:
            decoded[str(key)] = json.loads(str(value_json))
    return decoded
