"""Boot must rebind vault watchdog after DB vault_dir is applied.

Regression: default_vault_watchdog_factory resolves the vault BEFORE
``apply_persisted_settings_at_boot``, so a vault that lives only in the DB
left the watcher with ``vault_root=None`` and ``start()`` logged OFF forever.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from engine.protocol import EventBroadcastHub
from engine.server import create_app
from engine.storage.app_settings_repository import SETTING_VAULT_DIR, write_setting
from engine.storage.sqlite_connection import open_sqlite_connection
from engine.storage.sqlite_migrations_runner import apply_migrations
from engine.vault.vault_paths import VAULT_DIR_ENV_VAR
from engine.wiring.app_settings_command_gateway import AppSettingsCommandGateway
from engine.wiring.onboarding_settings_command_surface import (
    build_onboarding_settings_command_surface,
)
from engine.wiring.vault_watchdog_server_wiring import VaultWatchdogServerWiring
from tests.conftest import REPO_ROOT
from tests.test_server__lifespan_and_main_shutdown_paths import _HangingCaptureService
from tests.test_server__vault_watchdog_wiring import FakeWatcherStarter

MIGRATIONS = REPO_ROOT / "migrations"


def test_lifespan_rebinds_vault_watchdog_after_boot_applies_db_vault(
    tmp_db_path: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vault = tmp_path / "db-only-vault"
    vault.mkdir()

    async def _seed() -> None:
        await apply_migrations(tmp_db_path, MIGRATIONS)
        connection = await open_sqlite_connection(tmp_db_path)
        try:
            await write_setting(connection, SETTING_VAULT_DIR, str(vault))
            await connection.commit()
        finally:
            await connection.close()

    asyncio.run(_seed())
    monkeypatch.delenv(VAULT_DIR_ENV_VAR, raising=False)

    starter = FakeWatcherStarter()
    # Simulate factory resolving BEFORE boot (env unset → None root).
    watchdog = VaultWatchdogServerWiring(
        tmp_db_path, MIGRATIONS, vault_root=None, watcher_starter=starter
    )
    m7 = build_onboarding_settings_command_surface(
        EventBroadcastHub(),
        settings_gateway_factory=lambda: AppSettingsCommandGateway(tmp_db_path, MIGRATIONS),
    )
    app = create_app(
        capture_service_factory=_HangingCaptureService,
        preload_stt=True,
        m7_surface=m7,
        vault_watchdog_factory=lambda: watchdog,
    )

    with TestClient(app):
        assert watchdog.is_watching is True
        assert starter.calls == [vault]
