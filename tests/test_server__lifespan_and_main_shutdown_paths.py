"""Server lifespan + process-entrypoint paths, driven without a real socket.

These exercise the ``create_app`` lifespan's PRELOAD + full-shutdown branch
(preload task cancel, live-capture stop, and the vault-watchdog / spotter /
card-build shutdown calls) and ``main``'s fail-closed settings load + serve,
using Starlette's TestClient as a context manager (which runs startup on
enter and shutdown on exit) plus a fake, non-loading capture service so no
multi-GB model ever loads. The m7 surface is rebuilt against a tmp database
so the boot hook never touches the real settings store (synthetic only).
"""

import asyncio
from pathlib import Path
from typing import Any

import pytest
import uvicorn
from starlette.testclient import TestClient

import engine.server as server_module
from engine.protocol import EventBroadcastHub
from engine.server import create_app
from engine.stt.live_capture_service import LiveCaptureService
from engine.wiring.app_settings_command_gateway import AppSettingsCommandGateway
from engine.wiring.approval_card_build_server_wiring import ApprovalCardBuildWiring
from engine.wiring.live_answers_spotter_wiring import LiveAnswersSpotterWiring
from engine.wiring.onboarding_settings_command_surface import (
    build_onboarding_settings_command_surface,
)
from engine.wiring.vault_watchdog_server_wiring import VaultWatchdogServerWiring
from tests.conftest import REPO_ROOT

MIGRATIONS = REPO_ROOT / "migrations"


class _HangingCaptureService(LiveCaptureService):
    """Fake capture: ``preload_models`` hangs (so the lifespan must cancel it)
    and ``is_capturing`` stays True (so the lifespan must stop it) — every
    slow model load is replaced by a controllable coroutine."""

    def __init__(self, hub: EventBroadcastHub) -> None:
        super().__init__(db_path=Path("unused.db"), migrations_dir=Path("unused"), hub=hub)
        self._never = asyncio.Event()
        self.preload_started = False
        self.preload_cancelled = False
        self.stopped = False

    async def preload_models(self) -> None:
        self.preload_started = True
        try:
            await self._never.wait()
        except asyncio.CancelledError:
            self.preload_cancelled = True
            raise

    @property
    def is_capturing(self) -> bool:
        return True

    async def stop(self, reason: str = "command") -> str:
        self.stopped = True
        return "stopped"


def test_lifespan_preload_and_shutdown_cancel_preload_and_stop_capture(
    tmp_db_path: Path, tmp_path: Path
) -> None:
    throwaway_hub = EventBroadcastHub()
    m7 = build_onboarding_settings_command_surface(
        throwaway_hub,
        settings_gateway_factory=lambda: AppSettingsCommandGateway(tmp_db_path, MIGRATIONS),
    )
    app = create_app(
        capture_service_factory=_HangingCaptureService,
        preload_stt=True,
        m7_surface=m7,
        vault_watchdog_factory=lambda: VaultWatchdogServerWiring(
            tmp_db_path, MIGRATIONS, vault_root=None
        ),
        spotter_wiring_factory=lambda hub: LiveAnswersSpotterWiring(hub, tmp_db_path, MIGRATIONS),
        card_build_wiring_factory=lambda hub: ApprovalCardBuildWiring(hub, tmp_db_path, MIGRATIONS),
    )
    capture = app.state.capture_service
    assert isinstance(capture, _HangingCaptureService)
    # Every event-timer surface must actually be wired for its shutdown to run.
    assert app.state.vault_watchdog is not None
    assert app.state.spotter_wiring is not None
    assert app.state.card_build_wiring is not None

    with TestClient(app):
        # Startup ran: the preload task was created and began.
        pass

    # Shutdown ran the full teardown: the hanging preload was cancelled and the
    # still-capturing stream was stopped — no orphaned audio, no orphaned task.
    assert capture.preload_started is True
    assert capture.preload_cancelled is True
    assert capture.stopped is True


def test_main_configures_logging_loads_settings_and_serves(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``main`` must load settings (fail closed) and hand the built config to a
    uvicorn server it runs — verified without building the real app or a socket."""
    recorded: dict[str, Any] = {}

    class _FakeServer:
        def __init__(self, config: Any) -> None:
            recorded["config"] = config

        def run(self) -> None:
            recorded["ran"] = True

    sentinel_settings = object()
    sentinel_config = object()
    monkeypatch.setattr(server_module, "load_engine_settings", lambda: sentinel_settings)

    def fake_build(settings: Any) -> Any:
        recorded["settings_seen"] = settings
        return sentinel_config

    monkeypatch.setattr(server_module, "build_uvicorn_config", fake_build)
    # engine.server references the module-global ``uvicorn``; patching the
    # shared module object patches what ``main`` will call.
    monkeypatch.setattr(uvicorn, "Server", _FakeServer)

    server_module.main()

    # The loaded settings drove the config, and the server was actually run.
    assert recorded["settings_seen"] is sentinel_settings
    assert recorded["config"] is sentinel_config
    assert recorded["ran"] is True
