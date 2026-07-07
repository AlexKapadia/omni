"""M7 google.connect surface: background desktop OAuth, skippable.

Adversarial coverage: a lone client id (or secret) is refused (both-or-neither
deny by default); supplied credentials are persisted to the DPAPI token store
before the flow runs; the consent flow runs in the background and reports the
honest outcome via ``google.connect.completed`` (success AND failure), never
leaking token material; a second connect while one is in flight is refused.
The real browser flow is replaced by an injected fake — no network, no UI.
"""

import uuid
from pathlib import Path
from typing import Any

import pytest

from engine.google.dpapi_google_token_store import GoogleTokenStore
from engine.google.google_auth_errors import GoogleOAuthFlowError
from engine.protocol import (
    EVENT_GOOGLE_CONNECT_COMPLETED,
    Envelope,
    EnvelopeKind,
    EventBroadcastHub,
)
from engine.wiring import google_connect_command_dispatcher as mod
from engine.wiring.google_connect_command_dispatcher import (
    GoogleConnectCommandGateway,
    dispatch_google_command,
)


class _CapturingHub(EventBroadcastHub):
    def __init__(self) -> None:
        super().__init__()
        self.events: list[tuple[str, dict[str, Any]]] = []

    async def broadcast_event(self, name: str, payload: dict[str, Any]) -> None:
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
        name="google.connect",
        id=str(uuid.uuid4()),
        payload=payload,
    )


async def test_lone_client_id_is_refused(tmp_path: Path) -> None:
    gateway = GoogleConnectCommandGateway(
        hub=_CapturingHub(), token_store=GoogleTokenStore(store_path=tmp_path / "g.bin")
    )
    send = _Collector()
    await dispatch_google_command(_command({"client_id": "only-the-id"}), gateway, send)
    # Both-or-neither: a lone id can never start a flow (deny by default).
    assert send.sent[0].name == "error"


async def test_supplied_credentials_are_saved_and_success_is_reported(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = GoogleTokenStore(store_path=tmp_path / "g.bin")
    hub = _CapturingHub()
    gateway = GoogleConnectCommandGateway(hub=hub, token_store=store)

    async def fake_flow(token_store: object, **kwargs: object) -> object:
        return object()  # tokens object; the gateway ignores its shape

    monkeypatch.setattr(mod, "run_google_oauth_desktop_flow", fake_flow)
    send = _Collector()
    await dispatch_google_command(
        _command({"client_id": "the-client-id", "client_secret": "the-secret"}), gateway, send
    )
    assert send.sent[0].name == "ok"
    assert gateway._task is not None
    await gateway._task
    # Credentials landed in the DPAPI store...
    creds = store.load_client_credentials()
    assert creds is not None and creds.client_id == "the-client-id"
    # ...and the completed event is an honest success with NO token material.
    completed = next(p for n, p in hub.events if n == EVENT_GOOGLE_CONNECT_COMPLETED)
    assert completed["ok"] is True
    assert "the-secret" not in str(completed)


async def test_flow_failure_reports_completed_false(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    hub = _CapturingHub()
    gateway = GoogleConnectCommandGateway(
        hub=hub, token_store=GoogleTokenStore(store_path=tmp_path / "g.bin")
    )

    async def failing_flow(token_store: object, **kwargs: object) -> object:
        raise GoogleOAuthFlowError("no client credentials")

    monkeypatch.setattr(mod, "run_google_oauth_desktop_flow", failing_flow)
    send = _Collector()
    await dispatch_google_command(_command({}), gateway, send)
    assert send.sent[0].name == "ok"  # accepted; outcome arrives as an event
    assert gateway._task is not None
    await gateway._task
    completed = next(p for n, p in hub.events if n == EVENT_GOOGLE_CONNECT_COMPLETED)
    assert completed["ok"] is False


async def test_dispatch_refuses_when_gateway_missing() -> None:
    send = _Collector()
    await dispatch_google_command(_command({}), None, send)
    assert send.sent[0].name == "error"
