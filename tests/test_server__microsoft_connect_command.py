"""M7 microsoft.connect surface: background desktop OAuth."""

import uuid
from pathlib import Path

import pytest

from engine.microsoft.dpapi_microsoft_token_store import MicrosoftTokenStore
from engine.microsoft.microsoft_auth_errors import MicrosoftOAuthFlowError
from engine.protocol import (
    EVENT_MICROSOFT_CONNECT_COMPLETED,
    Envelope,
    EnvelopeKind,
    EventBroadcastHub,
)
from engine.wiring import microsoft_connect_command_dispatcher as mod
from engine.wiring.microsoft_connect_command_dispatcher import (
    MicrosoftConnectCommandGateway,
    dispatch_microsoft_command,
)


class _CapturingHub(EventBroadcastHub):
    def __init__(self) -> None:
        super().__init__()
        self.events: list[tuple[str, dict[str, object]]] = []

    async def broadcast_event(self, name: str, payload: dict[str, object]) -> None:
        self.events.append((name, payload))
        await super().broadcast_event(name, payload)


class _Collector:
    def __init__(self) -> None:
        self.sent: list[Envelope] = []

    async def __call__(self, envelope: Envelope) -> None:
        self.sent.append(envelope)


def _command(payload: dict[str, object]) -> Envelope:
    return Envelope(
        v=1,
        kind=EnvelopeKind.COMMAND,
        name="microsoft.connect",
        id=str(uuid.uuid4()),
        payload=payload,
    )


async def test_lone_client_id_is_refused(tmp_path: Path) -> None:
    hub = _CapturingHub()
    gateway = MicrosoftConnectCommandGateway(
        hub, token_store=MicrosoftTokenStore(store_path=tmp_path / "m.bin")
    )
    send = _Collector()
    await dispatch_microsoft_command(
        _command({"client_id": "only-id"}),
        gateway,
        send,
    )
    assert send.sent[0].name == "error"
    assert send.sent[0].payload["code"] == "microsoft_error"


async def test_connect_broadcasts_completed_on_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    hub = _CapturingHub()
    gateway = MicrosoftConnectCommandGateway(
        hub, token_store=MicrosoftTokenStore(store_path=tmp_path / "m.bin")
    )
    send = _Collector()

    async def _fake_flow(_store: MicrosoftTokenStore) -> None:
        return None

    monkeypatch.setattr(mod, "run_microsoft_oauth_desktop_flow", _fake_flow)
    await dispatch_microsoft_command(_command({}), gateway, send)
    assert send.sent[0].name == "ok"
    assert send.sent[0].payload["started"] is True
    assert gateway._task is not None
    await gateway._task
    completed = next(p for n, p in hub.events if n == EVENT_MICROSOFT_CONNECT_COMPLETED)
    assert completed["ok"] is True
    await gateway.shutdown()


async def test_connect_broadcasts_failure_on_oauth_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    hub = _CapturingHub()
    gateway = MicrosoftConnectCommandGateway(
        hub, token_store=MicrosoftTokenStore(store_path=tmp_path / "m.bin")
    )
    send = _Collector()

    async def _fail(_store: MicrosoftTokenStore) -> None:
        raise MicrosoftOAuthFlowError("consent failed")

    monkeypatch.setattr(mod, "run_microsoft_oauth_desktop_flow", _fail)
    await dispatch_microsoft_command(_command({}), gateway, send)
    assert gateway._task is not None
    await gateway._task
    completed = next(p for n, p in hub.events if n == EVENT_MICROSOFT_CONNECT_COMPLETED)
    assert completed["ok"] is False
    await gateway.shutdown()
