"""M7 settings surface: settings.get / settings.update / setup.status.

Adversarial coverage of the server-layer settings gateway + dispatcher:
deny-by-default on unknown keys and wrong-typed values, all-or-nothing batch
persistence, boolean strictness (no truthiness coercion), the real vault
writability probe, whitelist deny-by-default, the append-only history trail,
and the honest setup.status shape (key PRESENCE only, never key material).
"""

import uuid
from pathlib import Path

from engine.google.dpapi_google_token_store import GoogleTokenStore
from engine.protocol import Envelope, EnvelopeKind
from engine.security.provider_key_store import ProviderKeyStore
from engine.security.secret_redaction import SecretApiKey
from engine.storage.app_settings_repository import (
    SETTING_KEEP_AUDIO,
    SETTING_ONBOARDING_COMPLETE,
    SETTING_VAULT_DIR,
)
from engine.storage.sqlite_connection import open_sqlite_connection
from engine.storage.sqlite_migrations_runner import apply_migrations
from engine.wiring.app_settings_command_dispatcher import dispatch_settings_command
from engine.wiring.app_settings_command_gateway import AppSettingsCommandGateway


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


async def test_update_persists_and_get_reads_it_back(
    tmp_path: Path, real_migrations_dir: Path
) -> None:
    gateway = _gateway(tmp_path, real_migrations_dir)
    vault = tmp_path / "vault"
    vault.mkdir()
    send = _Collector()
    await dispatch_settings_command(
        _command("settings.update", {"values": {SETTING_VAULT_DIR: str(vault)}}), gateway, send
    )
    assert send.sent[0].name == "ok"
    assert send.sent[0].payload["applied"] == {SETTING_VAULT_DIR: str(vault)}

    got = _Collector()
    await dispatch_settings_command(_command("settings.get", {}), gateway, got)
    settings = got.sent[0].payload["settings"]
    assert settings[SETTING_VAULT_DIR] == str(vault)
    # keep_audio defaults ON: recordings are kept as MP3 alongside the transcript.
    assert settings[SETTING_KEEP_AUDIO] is True


async def test_unknown_key_is_refused_and_nothing_persists(
    tmp_path: Path, real_migrations_dir: Path
) -> None:
    gateway = _gateway(tmp_path, real_migrations_dir)
    send = _Collector()
    await dispatch_settings_command(
        _command("settings.update", {"values": {"totally_unknown_key": 1}}), gateway, send
    )
    reply = send.sent[0]
    assert reply.name == "error"
    assert reply.payload["code"] == "settings_error"
    # Deny by default: the whole batch is refused; the table stays empty.
    await apply_migrations(gateway._db_path, real_migrations_dir)
    connection = await open_sqlite_connection(gateway._db_path)
    try:
        cursor = await connection.execute("SELECT COUNT(*) FROM app_settings")
        (count,) = await cursor.fetchone()  # type: ignore[misc]
    finally:
        await connection.close()
    assert count == 0


async def test_boolean_setting_rejects_truthy_non_bool(
    tmp_path: Path, real_migrations_dir: Path
) -> None:
    gateway = _gateway(tmp_path, real_migrations_dir)
    send = _Collector()
    # 1 is truthy but NOT a JSON boolean — strictness is the security posture.
    await dispatch_settings_command(
        _command("settings.update", {"values": {SETTING_KEEP_AUDIO: 1}}), gateway, send
    )
    assert send.sent[0].name == "error"


async def test_all_or_nothing_one_bad_key_rolls_back_the_valid_one(
    tmp_path: Path, real_migrations_dir: Path
) -> None:
    gateway = _gateway(tmp_path, real_migrations_dir)
    send = _Collector()
    await dispatch_settings_command(
        _command(
            "settings.update",
            {"values": {SETTING_ONBOARDING_COMPLETE: True, SETTING_KEEP_AUDIO: "nope"}},
        ),
        gateway,
        send,
    )
    assert send.sent[0].name == "error"
    got = _Collector()
    await dispatch_settings_command(_command("settings.get", {}), gateway, got)
    # The VALID key must NOT have landed — the batch is atomic.
    assert got.sent[0].payload["settings"][SETTING_ONBOARDING_COMPLETE] is False


async def test_vault_dir_that_cannot_be_written_is_refused(
    tmp_path: Path, real_migrations_dir: Path
) -> None:
    gateway = _gateway(tmp_path, real_migrations_dir)
    send = _Collector()
    missing = tmp_path / "does-not-exist"
    await dispatch_settings_command(
        _command("settings.update", {"values": {SETTING_VAULT_DIR: str(missing)}}), gateway, send
    )
    # Without create_vault_dir, a missing folder is refused (fail closed).
    assert send.sent[0].name == "error"


async def test_create_vault_dir_flag_makes_the_folder(
    tmp_path: Path, real_migrations_dir: Path
) -> None:
    gateway = _gateway(tmp_path, real_migrations_dir)
    send = _Collector()
    fresh = tmp_path / "fresh-vault"
    # The create_vault_dir companion flag rides INSIDE the values map (the
    # envelope forbids extra top-level fields); it is consumed, not persisted.
    await dispatch_settings_command(
        _command(
            "settings.update",
            {"values": {SETTING_VAULT_DIR: str(fresh), "create_vault_dir": True}},
        ),
        gateway,
        send,
    )
    assert send.sent[0].name == "ok"
    assert fresh.is_dir()
    # The companion flag is consumed, never persisted as a setting.
    assert "create_vault_dir" not in send.sent[0].payload["applied"]


async def test_whitelist_rejects_unknown_intent_type(
    tmp_path: Path, real_migrations_dir: Path
) -> None:
    gateway = _gateway(tmp_path, real_migrations_dir)
    send = _Collector()
    await dispatch_settings_command(
        _command(
            "settings.update",
            {"values": {"instant_execute_whitelist": ["create_event", "launch_missiles"]}},
        ),
        gateway,
        send,
    )
    # Deny by default: one unknown intent type refuses the whole value.
    assert send.sent[0].name == "error"


async def test_history_trail_appends_a_row_per_change(
    tmp_path: Path, real_migrations_dir: Path
) -> None:
    gateway = _gateway(tmp_path, real_migrations_dir)
    for value in (True, False, True):
        send = _Collector()
        await dispatch_settings_command(
            _command("settings.update", {"values": {SETTING_ONBOARDING_COMPLETE: value}}),
            gateway,
            send,
        )
        assert send.sent[0].name == "ok"
    connection = await open_sqlite_connection(gateway._db_path)
    try:
        cursor = await connection.execute(
            "SELECT COUNT(*) FROM app_settings_history WHERE key = ?",
            (SETTING_ONBOARDING_COMPLETE,),
        )
        (rows,) = await cursor.fetchone()  # type: ignore[misc]
    finally:
        await connection.close()
    # Append-only audit: three writes leave three history rows, never fewer.
    assert rows == 3


async def test_setup_status_reports_presence_only_and_completion_gate(
    tmp_path: Path, real_migrations_dir: Path
) -> None:
    gateway = _gateway(tmp_path, real_migrations_dir, keyed=("groq", "gemini"))
    send = _Collector()
    await dispatch_settings_command(_command("setup.status", {}), gateway, send)
    payload = send.sent[0].payload
    assert payload["keys"] == {
        "groq": True,
        "gemini": True,
        "anthropic": False,
        "openai": False,
        "openrouter": False,
        "azure_openai": False,
        "cartesia": False,
    }
    # No key MATERIAL anywhere in the reply — presence booleans only.
    assert "test-key-value" not in send.sent[0].to_wire()
    # Required pair present but no vault + no models => setup NOT complete.
    assert payload["setup_complete"] is False


async def test_settings_dispatch_refuses_when_gateway_missing() -> None:
    send = _Collector()
    await dispatch_settings_command(_command("settings.get", {}), None, send)
    assert send.sent[0].name == "error"
    assert send.sent[0].payload["code"] == "settings_error"
