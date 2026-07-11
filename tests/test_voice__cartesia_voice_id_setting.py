"""cartesia_voice_id setting mirrors into CARTESIA_VOICE_ID (setting wins)."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from engine.voice.cartesia_credentials import (
    CARTESIA_API_KEY_ENV_VAR,
    CARTESIA_VOICE_ID_ENV_VAR,
    load_cartesia_credentials,
)
from engine.wiring.app_settings_command_gateway import (
    SETTINGS_DEFAULTS,
    AppSettingsCommandGateway,
)
from engine.storage import app_settings_repository as settings_repo

FAKE_KEY = "sk-cartesia-test-key-0000"
SETTING_CARTESIA_VOICE_ID = "cartesia_voice_id"


def test_cartesia_voice_id_is_a_known_settings_key() -> None:
    assert SETTING_CARTESIA_VOICE_ID in settings_repo.KNOWN_SETTINGS_KEYS
    assert hasattr(settings_repo, "SETTING_CARTESIA_VOICE_ID")
    assert SETTINGS_DEFAULTS[SETTING_CARTESIA_VOICE_ID] == ""


@pytest.mark.asyncio
async def test_settings_update_mirrors_cartesia_voice_id_into_env(
    tmp_path: Path, real_migrations_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv(CARTESIA_VOICE_ID_ENV_VAR, raising=False)
    gateway = AppSettingsCommandGateway(tmp_path / "app.db", real_migrations_dir)
    await gateway.update_settings({SETTING_CARTESIA_VOICE_ID: "voice-from-settings"})
    assert os.environ.get(CARTESIA_VOICE_ID_ENV_VAR) == "voice-from-settings"


@pytest.mark.asyncio
async def test_load_credentials_uses_mirrored_voice_id_from_setting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(CARTESIA_API_KEY_ENV_VAR, FAKE_KEY)
    monkeypatch.setenv(CARTESIA_VOICE_ID_ENV_VAR, "voice-from-settings")
    creds = load_cartesia_credentials()
    assert creds.voice_id == "voice-from-settings"


@pytest.mark.asyncio
async def test_clearing_cartesia_voice_id_pops_env(
    tmp_path: Path, real_migrations_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(CARTESIA_VOICE_ID_ENV_VAR, "stale-voice")
    gateway = AppSettingsCommandGateway(tmp_path / "app.db", real_migrations_dir)
    await gateway.update_settings({SETTING_CARTESIA_VOICE_ID: "voice-a"})
    assert os.environ.get(CARTESIA_VOICE_ID_ENV_VAR) == "voice-a"
    await gateway.update_settings({SETTING_CARTESIA_VOICE_ID: "   "})
    assert CARTESIA_VOICE_ID_ENV_VAR not in os.environ
