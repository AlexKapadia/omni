"""Omni engine sidecar package.

Purpose: the Python engine process that the Tauri UI supervises as a sidecar.
Pipeline position: root package — audio capture, STT, indexing, routing, and
agent execution all live in subpackages; ``engine.server`` is the entrypoint.

Security invariants upheld package-wide:
- The engine binds to 127.0.0.1 only (never 0.0.0.0) — see ``engine.server``.
- No telemetry of any kind is emitted by any module in this package.
"""

# Single source of truth for the engine version, reported by GET /health and
# the engine.heartbeat event so the UI can detect sidecar/UI version skew.
ENGINE_VERSION = "0.1.0"
