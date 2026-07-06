"""Engine HTTP + WebSocket server and process entrypoint.

Purpose: hosts the pinned surface the UI talks to — GET /health and the
ws://127.0.0.1:<port>/ws protocol-v1 endpoint — and owns process startup
and graceful shutdown. Run with ``python -m engine.server``.
Pipeline position: the outermost shell of the engine sidecar; everything
else in ``engine.*`` is reached through the routes defined here.

Security invariants:
- Binds to 127.0.0.1 ONLY (``LOOPBACK_HOST`` constant) — the engine must
  never be reachable from another machine (local-only invariant).
- Startup fails closed: malformed settings abort the process rather than
  boot on guessed configuration.
- No telemetry: the server calls out to nothing; it only answers. (The
  one exception is the explicit, user-initiated model download tool.)
- Shutdown stops any live capture session so no orphaned audio streams
  outlive the process.
"""

import asyncio
import contextlib
import logging
import time
from collections.abc import AsyncIterator, Callable
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import FastAPI, WebSocket

from engine import ENGINE_VERSION
from engine.enhance import MeetingFinalizationService
from engine.protocol import EventBroadcastHub
from engine.runtime_settings import LOOPBACK_HOST, EngineSettings, load_engine_settings
from engine.stt.live_capture_service import LiveCaptureService
from engine.voice import TtsPlaybackStreamer
from engine.websocket_connection_handler import WebSocketConnectionHandler

# The repo's migrations directory (packaging bundles it next to the engine).
MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "migrations"

# A factory (not an instance) so the service is built AFTER settings load,
# against the hub the app owns. Tests inject fakes through this seam.
CaptureServiceFactory = Callable[[EventBroadcastHub], LiveCaptureService]


def _default_capture_service_factory(hub: EventBroadcastHub) -> LiveCaptureService:
    settings = load_engine_settings()  # Raises on bad env — fail closed.
    return LiveCaptureService(db_path=settings.db_path, migrations_dir=MIGRATIONS_DIR, hub=hub)


# Same factory seam as capture: built AFTER settings load, tests inject fakes.
FinalizationServiceFactory = Callable[[EventBroadcastHub], MeetingFinalizationService]


def _default_finalization_service_factory(hub: EventBroadcastHub) -> MeetingFinalizationService:
    settings = load_engine_settings()  # Raises on bad env — fail closed.
    # Construction is inert (no keys, no I/O): providers/vault resolve per
    # finalize call, so a missing key refuses that call, never engine boot.
    return MeetingFinalizationService(
        db_path=settings.db_path, migrations_dir=MIGRATIONS_DIR, hub=hub
    )


def create_app(
    capture_service_factory: CaptureServiceFactory | None = None,
    preload_stt: bool = False,
    finalization_service_factory: FinalizationServiceFactory | None = None,
) -> FastAPI:
    """Build the FastAPI app. Factory form keeps tests isolated per-app.

    ``preload_stt`` starts a background model load at boot so the
    heartbeat's ``stt_ready`` flips true before the first capture.start;
    it defaults OFF so tests (and tooling) never trigger multi-GB loads.
    """
    event_hub = EventBroadcastHub()
    factory = capture_service_factory or _default_capture_service_factory
    capture_service = factory(event_hub)
    # Naomi voice: relays Cartesia audio to every socket via the same hub.
    # Construction is inert (credentials resolve lazily per utterance).
    voice_streamer = TtsPlaybackStreamer(event_hub)
    # M2 meeting library/finalization: same hub, inert construction.
    finalization_factory = finalization_service_factory or _default_finalization_service_factory
    finalization_service = finalization_factory(event_hub)

    @contextlib.asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        """Startup: clocks + optional model preload. Shutdown: stop capture."""
        app.state.started_monotonic = time.monotonic()
        preload_task: asyncio.Task[None] | None = None
        if preload_stt:
            # Background: heartbeats flow (stt_ready=false) while models load.
            preload_task = asyncio.create_task(capture_service.preload_models())
        yield
        if preload_task is not None and not preload_task.done():
            preload_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await preload_task
        if capture_service.is_capturing:
            # Graceful shutdown: never orphan live audio streams.
            with contextlib.suppress(Exception):
                await capture_service.stop()
        # Graceful shutdown: never orphan a speaking utterance either.
        with contextlib.suppress(Exception):
            await voice_streamer.shutdown()

    app = FastAPI(
        title="omni-engine",
        version=ENGINE_VERSION,
        # No public docs surface: the engine is a private local sidecar,
        # not a browsable API (minimise attack/discovery surface).
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
    )
    app.state.event_hub = event_hub
    app.state.capture_service = capture_service
    app.state.voice_streamer = voice_streamer
    app.state.finalization_service = finalization_service

    @app.get("/health")
    async def health() -> dict[str, Any]:
        """Liveness probe for the UI supervisor and the packaging smoke test."""
        return {"status": "ok", "version": ENGINE_VERSION}

    @app.websocket("/ws")
    async def websocket_endpoint(websocket: WebSocket) -> None:
        """Protocol v1 endpoint: accept, then hand off to the handler."""
        await websocket.accept()
        handler = WebSocketConnectionHandler(
            websocket=websocket,
            started_monotonic=websocket.app.state.started_monotonic,
            capture_service=websocket.app.state.capture_service,
            event_hub=websocket.app.state.event_hub,
            voice_streamer=websocket.app.state.voice_streamer,
            finalization_service=websocket.app.state.finalization_service,
        )
        await handler.run()

    return app


def build_uvicorn_config(settings: EngineSettings) -> uvicorn.Config:
    """Translate validated settings into the uvicorn config.

    Split out from ``main`` so tests can assert the binding contract
    (loopback-only host, env-driven port) without opening a socket.
    """
    return uvicorn.Config(
        # Production app preloads STT so stt_ready flips true at boot.
        app=create_app(preload_stt=True),
        # Local-only invariant: loopback constant, never a setting.
        host=LOOPBACK_HOST,
        port=settings.engine_port,
        log_level="info",
        # The Tauri supervisor restarts us; workers stay at 1 so there is
        # exactly one heartbeat/state owner per process.
        workers=1,
    )


def main() -> None:
    """Process entrypoint: load settings (fail closed) and serve until signalled."""
    # Root logging at INFO: the engine log is the audit surface for capture
    # lifecycle and the 60 s p50/p95 latency lines (instrumentation mandate)
    # — uvicorn only configures its own loggers, never the root.
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    settings = load_engine_settings()  # Raises on bad env — fail closed.
    server = uvicorn.Server(build_uvicorn_config(settings))
    # uvicorn installs SIGINT/SIGTERM handlers → graceful shutdown of the
    # event loop and open WebSockets.
    server.run()


if __name__ == "__main__":
    main()
