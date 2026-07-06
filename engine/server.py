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
- No telemetry: the server calls out to nothing; it only answers.
"""

import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import uvicorn
from fastapi import FastAPI, WebSocket

from engine import ENGINE_VERSION
from engine.runtime_settings import LOOPBACK_HOST, EngineSettings, load_engine_settings
from engine.websocket_connection_handler import WebSocketConnectionHandler


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Record process start time (monotonic — uptime survives clock changes).

    Uvicorn drives this on startup/shutdown, so exiting the context is the
    graceful-shutdown hook for any future resources (DB pools, tasks).
    """
    app.state.started_monotonic = time.monotonic()
    yield
    # Graceful shutdown: per-connection tasks are cancelled by their own
    # handlers on disconnect; nothing process-wide to tear down in M0.


def create_app() -> FastAPI:
    """Build the FastAPI app. Factory form keeps tests isolated per-app."""
    app = FastAPI(
        title="omni-engine",
        version=ENGINE_VERSION,
        # No public docs surface: the engine is a private local sidecar,
        # not a browsable API (minimise attack/discovery surface).
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=_lifespan,
    )

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
        )
        await handler.run()

    return app


def build_uvicorn_config(settings: EngineSettings) -> uvicorn.Config:
    """Translate validated settings into the uvicorn config.

    Split out from ``main`` so tests can assert the binding contract
    (loopback-only host, env-driven port) without opening a socket.
    """
    return uvicorn.Config(
        app=create_app(),
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
    settings = load_engine_settings()  # Raises on bad env — fail closed.
    server = uvicorn.Server(build_uvicorn_config(settings))
    # uvicorn installs SIGINT/SIGTERM handlers → graceful shutdown of the
    # event loop and open WebSockets.
    server.run()


if __name__ == "__main__":
    main()
