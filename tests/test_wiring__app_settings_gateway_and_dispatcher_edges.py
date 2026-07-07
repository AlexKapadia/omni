"""Edge-path tests for the settings gateway, dispatcher, M7 surface + repo.

Covers the uncovered error/side-effect branches with real behaviour
assertions: the routing-rows success path (attempts + budget), the
all-or-nothing rollback (nothing persists when a write fails mid-batch),
the kill-switch runtime side effect, the boot hook's env/kill-switch
application (and its "explicit env wins" guard), a corrupt Google token
blob reading as not-connected, the dispatcher's invalid-payload and
generic-failure replies, the M7 router's per-family dispatch, and the
repository's unknown-key refusal. All state is synthetic (``tmp_path``).
"""

import os
import uuid
from pathlib import Path
from typing import Any

import pytest

from engine.google.dpapi_google_token_store import GoogleTokenStore
from engine.protocol import Envelope, EnvelopeKind
from engine.security.kill_switch import (
    kill_switch_engaged,
    set_kill_switch_runtime_override,
)
from engine.security.provider_key_store import ProviderKeyStore
from engine.security.secret_redaction import SecretApiKey
from engine.storage.app_settings_repository import (
    SETTING_KILL_SWITCH,
    SETTING_VAULT_DIR,
    UnknownSettingsKeyError,
    write_setting,
)
from engine.storage.sqlite_connection import open_sqlite_connection
from engine.storage.sqlite_migrations_runner import apply_migrations
from engine.vault.vault_paths import VAULT_DIR_ENV_VAR
from engine.wiring import app_settings_command_gateway as gateway_module
from engine.wiring.app_settings_command_dispatcher import (
    SETTINGS_COMMAND_NAMES,
    dispatch_settings_command,
)
from engine.wiring.app_settings_command_gateway import AppSettingsCommandGateway
from engine.wiring.google_connect_command_dispatcher import GOOGLE_COMMAND_NAMES
from engine.wiring.ledger_summary_command_dispatcher import LEDGER_COMMAND_NAMES
from engine.wiring.models_download_command_dispatcher import MODELS_COMMAND_NAMES
from engine.wiring.onboarding_settings_command_surface import (
    OnboardingSettingsCommandSurface,
    dispatch_m7_command,
)
from engine.wiring.provider_keys_command_dispatcher import KEYS_COMMAND_NAMES


class _Collector:
    """Fake send: records every reply envelope for assertions."""

    def __init__(self) -> None:
        self.sent: list[Envelope] = []

    async def __call__(self, envelope: Envelope) -> None:
        self.sent.append(envelope)


def _command(name: str, payload: dict[str, object]) -> Envelope:
    return Envelope(
        v=1, kind=EnvelopeKind.COMMAND, name=name, id=str(uuid.uuid4()), payload=payload
    )


def _gateway(
    tmp_path: Path, real_migrations_dir: Path, *, keyed: tuple[str, ...] = ()
) -> AppSettingsCommandGateway:
    key_store = ProviderKeyStore(store_path=tmp_path / "keys.bin")
    for provider in keyed:
        key_store.set_key(provider, SecretApiKey(f"{provider}-test-key-value"))
    return AppSettingsCommandGateway(
        db_path=tmp_path / "omni.db",
        migrations_dir=real_migrations_dir,
        key_store=key_store,
        models_dir=tmp_path / "models",
        google_token_store=GoogleTokenStore(store_path=tmp_path / "google.bin"),
    )


async def _row_count(db_path: Path, real_migrations_dir: Path) -> int:
    await apply_migrations(db_path, real_migrations_dir)
    connection = await open_sqlite_connection(db_path)
    try:
        cursor = await connection.execute("SELECT COUNT(*) FROM app_settings")
        row = await cursor.fetchone()
        assert row is not None
        return int(row[0])
    finally:
        await connection.close()


# --------------------------------------------------------- routing rows path
async def test_routing_rows_include_resolved_attempts_for_keyed_task(
    tmp_path: Path, real_migrations_dir: Path
) -> None:
    gateway = _gateway(tmp_path, real_migrations_dir, keyed=("groq", "gemini"))
    payload = await gateway.get_settings_payload()
    routing = payload["routing"]
    assert isinstance(routing, list)
    routed = [r for r in routing if r["on_device"] is False]
    # With groq+gemini keyed, at least one task resolves to real attempts.
    served = [r for r in routed if r["attempts"]]
    assert served, "expected at least one keyed task to resolve to a provider"
    for row in served:
        assert isinstance(row["attempts"], list)
        for attempt in row["attempts"]:
            assert set(attempt) == {"provider", "model"}
        assert row["budget_ms"] is None or isinstance(row["budget_ms"], int)


# ------------------------------------------------------- all-or-nothing rollback
async def test_update_rolls_back_when_a_write_fails_midbatch(
    tmp_path: Path, real_migrations_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    gateway = _gateway(tmp_path, real_migrations_dir)

    async def _boom(*_args: Any, **_kwargs: Any) -> None:
        raise RuntimeError("disk full mid-write")

    # The gateway imported write_setting by name; patch it there.
    monkeypatch.setattr(gateway_module, "write_setting", _boom)
    with pytest.raises(RuntimeError, match="disk full mid-write"):
        await gateway.update_settings({SETTING_KILL_SWITCH: True})
    # ROLLBACK must have fired: the batch persisted NOTHING.
    monkeypatch.undo()
    assert await _row_count(gateway._db_path, real_migrations_dir) == 0


# ----------------------------------------------------- kill-switch side effect
async def test_update_kill_switch_engages_runtime_override(
    tmp_path: Path, real_migrations_dir: Path
) -> None:
    gateway = _gateway(tmp_path, real_migrations_dir)
    try:
        await gateway.update_settings({SETTING_KILL_SWITCH: True})
        assert kill_switch_engaged() is True  # side effect: instant egress halt
        await gateway.update_settings({SETTING_KILL_SWITCH: False})
        assert kill_switch_engaged() is False
    finally:
        set_kill_switch_runtime_override(None)  # neutralise global for other tests


# ----------------------------------------------------------- boot hook effects
async def test_boot_hook_applies_stored_vault_and_kill_switch(
    tmp_path: Path, real_migrations_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    gateway = _gateway(tmp_path, real_migrations_dir)
    vault = tmp_path / "boot-vault"
    vault.mkdir()
    await apply_migrations(gateway._db_path, real_migrations_dir)
    connection = await open_sqlite_connection(gateway._db_path)
    try:
        await write_setting(connection, SETTING_VAULT_DIR, str(vault))
        await write_setting(connection, SETTING_KILL_SWITCH, True)
        await connection.commit()
    finally:
        await connection.close()

    monkeypatch.delenv(VAULT_DIR_ENV_VAR, raising=False)
    set_kill_switch_runtime_override(None)
    try:
        await gateway.apply_persisted_settings_at_boot()
        # vault_dir mirrored into the env (it was unset); kill switch engaged.
        assert os.environ[VAULT_DIR_ENV_VAR] == str(vault)
        assert kill_switch_engaged() is True
    finally:
        set_kill_switch_runtime_override(None)


async def test_boot_hook_does_not_override_explicit_env_vault(
    tmp_path: Path, real_migrations_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    gateway = _gateway(tmp_path, real_migrations_dir)
    stored = tmp_path / "stored-vault"
    stored.mkdir()
    await apply_migrations(gateway._db_path, real_migrations_dir)
    connection = await open_sqlite_connection(gateway._db_path)
    try:
        await write_setting(connection, SETTING_VAULT_DIR, str(stored))
        await connection.commit()
    finally:
        await connection.close()

    monkeypatch.setenv(VAULT_DIR_ENV_VAR, "C:/explicit/env/vault")
    set_kill_switch_runtime_override(None)
    try:
        await gateway.apply_persisted_settings_at_boot()
        # Explicit env value wins at boot — the stored value must NOT clobber it.
        assert os.environ[VAULT_DIR_ENV_VAR] == "C:/explicit/env/vault"
    finally:
        set_kill_switch_runtime_override(None)


# ------------------------------------------------------- google token failure
async def test_setup_status_treats_corrupt_google_blob_as_not_connected(
    tmp_path: Path, real_migrations_dir: Path
) -> None:
    class _RaisingTokenStore:
        def load_tokens(self) -> object:
            raise RuntimeError("corrupt token blob")

    raising: Any = _RaisingTokenStore()
    gateway = AppSettingsCommandGateway(
        db_path=tmp_path / "omni.db",
        migrations_dir=real_migrations_dir,
        key_store=ProviderKeyStore(store_path=tmp_path / "keys.bin"),
        models_dir=tmp_path / "models",
        google_token_store=raising,
    )
    payload = await gateway.setup_status_payload()
    assert payload["google_connected"] is False


# ------------------------------------------------------------- dispatcher edges
async def test_dispatch_update_invalid_payload_shape_is_invalid_payload_error(
    tmp_path: Path, real_migrations_dir: Path
) -> None:
    gateway = _gateway(tmp_path, real_migrations_dir)
    send = _Collector()
    # ``values`` must be a non-empty map; a string fails pydantic validation.
    await dispatch_settings_command(
        _command("settings.update", {"values": "not-a-map"}), gateway, send
    )
    reply = send.sent[0]
    assert reply.name == "error"
    assert reply.payload["code"] == "invalid_payload"
    assert "payload failed validation" in str(reply.payload["message"])


async def test_dispatch_update_generic_failure_is_framed_settings_error() -> None:
    class _RaisingGateway:
        async def update_settings(self, _values: dict[str, object]) -> dict[str, object]:
            raise RuntimeError("unexpected engine fault")

    gateway: Any = _RaisingGateway()
    send = _Collector()
    await dispatch_settings_command(
        _command("settings.update", {"values": {"keep_audio": True}}), gateway, send
    )
    reply = send.sent[0]
    assert reply.name == "error"
    assert reply.payload["code"] == "settings_error"
    # Generic faults are framed opaquely (no internal detail leaks to the wire).
    assert reply.payload["message"] == "the settings update failed"


# ---------------------------------------------------------- M7 surface routing
async def test_m7_dispatch_each_family_refuses_when_surface_unwired() -> None:
    for names in (
        SETTINGS_COMMAND_NAMES,
        KEYS_COMMAND_NAMES,
        LEDGER_COMMAND_NAMES,
        MODELS_COMMAND_NAMES,
        GOOGLE_COMMAND_NAMES,
    ):
        send = _Collector()
        await dispatch_m7_command(_command(next(iter(names)), {}), None, send)
        # Deny by default: an unwired surface refuses honestly, never crashes.
        assert send.sent[0].name == "error"


async def test_m7_dispatch_routes_settings_get_to_settings_gateway() -> None:
    marker_payload: dict[str, object] = {"settings": {"marker": "routed-here"}}

    class _FakeSettingsGateway:
        async def get_settings_payload(self) -> dict[str, object]:
            return marker_payload

    settings_gw: Any = _FakeSettingsGateway()
    other: Any = object()
    surface = OnboardingSettingsCommandSurface(
        settings_gateway=settings_gw,
        keys_gateway=other,
        ledger_gateway=other,
        models_gateway=other,
        google_gateway=other,
    )
    send = _Collector()
    await dispatch_m7_command(_command("settings.get", {}), surface, send)
    reply = send.sent[0]
    assert reply.name == "ok"
    assert reply.payload == marker_payload  # proves it hit THIS gateway


async def test_surface_boot_hook_invokes_settings_gateway() -> None:
    calls: list[str] = []

    class _RecordingSettingsGateway:
        async def apply_persisted_settings_at_boot(self) -> None:
            calls.append("boot")

    settings_gw: Any = _RecordingSettingsGateway()
    other: Any = object()
    surface = OnboardingSettingsCommandSurface(
        settings_gateway=settings_gw,
        keys_gateway=other,
        ledger_gateway=other,
        models_gateway=other,
        google_gateway=other,
    )
    await surface.apply_persisted_settings_at_boot()
    assert calls == ["boot"]  # the boot hook actually delegated


async def test_surface_boot_hook_suppresses_gateway_exception() -> None:
    class _FailingSettingsGateway:
        async def apply_persisted_settings_at_boot(self) -> None:
            raise RuntimeError("boot failed")

    settings_gw: Any = _FailingSettingsGateway()
    other: Any = object()
    surface = OnboardingSettingsCommandSurface(
        settings_gateway=settings_gw,
        keys_gateway=other,
        ledger_gateway=other,
        models_gateway=other,
        google_gateway=other,
    )
    # Fail-soft: a boot-hook failure must NOT propagate (never crashes engine boot).
    await surface.apply_persisted_settings_at_boot()


# ----------------------------------------------------------- repository refusal
async def test_write_setting_refuses_unknown_key(
    tmp_path: Path, real_migrations_dir: Path
) -> None:
    db_path = tmp_path / "omni.db"
    await apply_migrations(db_path, real_migrations_dir)
    connection = await open_sqlite_connection(db_path)
    try:
        with pytest.raises(UnknownSettingsKeyError) as excinfo:
            await write_setting(connection, "not_a_real_key", 1)
    finally:
        await connection.close()
    assert excinfo.value.key == "not_a_real_key"
    assert "not_a_real_key" in str(excinfo.value)
