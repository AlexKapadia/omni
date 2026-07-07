"""M7 provider-keys surface: keys.save / keys.validate.

Adversarial coverage: a saved key round-trips into DPAPI custody and is NEVER
echoed back on the wire; the kill switch fails validation closed (no external
call); an un-keyed provider validates to a plain 'no key' result; and the
payload deny-by-default rejects unknown providers and out-of-bounds keys.
No network is touched (the tested paths return before any provider call).
"""

import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest

from engine.protocol import Envelope, EnvelopeKind
from engine.security.kill_switch import set_kill_switch_runtime_override
from engine.security.provider_key_store import ProviderKeyStore
from engine.wiring.provider_keys_command_dispatcher import (
    ProviderKeysCommandGateway,
    dispatch_keys_command,
)

_SECRET = "gsk_this_is_a_test_key_value_9f2c"  # noqa: S105 - synthetic fixture value


class _Collector:
    def __init__(self) -> None:
        self.sent: list[Envelope] = []

    async def __call__(self, envelope: Envelope) -> None:
        self.sent.append(envelope)


def _command(name: str, payload: dict[str, object]) -> Envelope:
    return Envelope(
        v=1, kind=EnvelopeKind.COMMAND, name=name, id=str(uuid.uuid4()), payload=payload
    )


@pytest.fixture()
def _no_kill_switch() -> Iterator[None]:
    # Ensure a clean runtime override around each test (the env var is unset
    # in CI; the override is process-global).
    set_kill_switch_runtime_override(None)
    yield
    set_kill_switch_runtime_override(None)


async def test_save_round_trips_into_dpapi_and_never_echoes_key(
    tmp_path: Path, _no_kill_switch: None
) -> None:
    store = ProviderKeyStore(store_path=tmp_path / "keys.bin")
    gateway = ProviderKeysCommandGateway(key_store=store)
    send = _Collector()
    await dispatch_keys_command(
        _command("keys.save", {"provider": "groq", "key": _SECRET}), gateway, send
    )
    assert send.sent[0].name == "ok"
    # The key is now in custody...
    saved = store.get_key("groq")
    assert saved is not None and saved.reveal() == _SECRET
    # ...but the plaintext NEVER appears in the reply frame (DPAPI binding).
    assert _SECRET not in send.sent[0].to_wire()


async def test_validate_fails_closed_when_kill_switch_engaged(
    tmp_path: Path, _no_kill_switch: None
) -> None:
    store = ProviderKeyStore(store_path=tmp_path / "keys.bin")
    store_gateway = ProviderKeysCommandGateway(key_store=store)
    # Save a key so the ONLY reason validation can fail is the kill switch.
    await dispatch_keys_command(
        _command("keys.save", {"provider": "groq", "key": _SECRET}),
        store_gateway,
        _Collector(),
    )
    set_kill_switch_runtime_override(True)  # fail closed on egress
    send = _Collector()
    await dispatch_keys_command(
        _command("keys.validate", {"provider": "groq"}), store_gateway, send
    )
    reply = send.sent[0].payload
    assert reply["valid"] is False
    assert "kill switch" in str(reply["message"]).lower()
    assert reply["latency_ms"] is None


async def test_validate_reports_no_key_honestly(tmp_path: Path, _no_kill_switch: None) -> None:
    store = ProviderKeyStore(store_path=tmp_path / "empty.bin")
    gateway = ProviderKeysCommandGateway(key_store=store)
    send = _Collector()
    await dispatch_keys_command(
        _command("keys.validate", {"provider": "anthropic"}), gateway, send
    )
    reply = send.sent[0].payload
    assert reply["valid"] is False
    assert "no key" in str(reply["message"]).lower()


async def test_unknown_provider_is_refused_by_payload(
    tmp_path: Path, _no_kill_switch: None
) -> None:
    gateway = ProviderKeysCommandGateway(key_store=ProviderKeyStore(store_path=tmp_path / "k.bin"))
    send = _Collector()
    await dispatch_keys_command(
        _command("keys.save", {"provider": "openai", "key": _SECRET}), gateway, send
    )
    # 'openai' is outside the closed provider enum — invalid payload.
    assert send.sent[0].name == "error"


async def test_too_short_key_is_refused(tmp_path: Path, _no_kill_switch: None) -> None:
    gateway = ProviderKeysCommandGateway(key_store=ProviderKeyStore(store_path=tmp_path / "k.bin"))
    send = _Collector()
    await dispatch_keys_command(
        _command("keys.save", {"provider": "groq", "key": "short"}), gateway, send
    )
    assert send.sent[0].name == "error"


async def test_dispatch_refuses_when_gateway_missing(_no_kill_switch: None) -> None:
    send = _Collector()
    await dispatch_keys_command(_command("keys.validate", {"provider": "groq"}), None, send)
    assert send.sent[0].name == "error"
    assert send.sent[0].payload["code"] == "keys_error"
