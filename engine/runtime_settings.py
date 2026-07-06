"""Runtime settings for the engine process, loaded from environment variables.

Purpose: one typed, validated place where every environment-driven knob is
declared, so no module reads ``os.environ`` ad hoc.
Pipeline position: imported by ``engine.server`` (port) and
``engine.storage`` (database path) at process start.

Security invariants:
- ``bind_host`` is a constant ``127.0.0.1`` and is deliberately NOT
  environment-overridable: the engine must never listen on a public
  interface (local-only invariant).
- Settings validation fails closed: an unparseable OMNI_ENGINE_PORT aborts
  startup instead of silently falling back to a default.
"""

import os
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# Local-only invariant: loopback interface, never configurable, never 0.0.0.0.
LOOPBACK_HOST = "127.0.0.1"

# Heartbeat cadence pinned by the WS protocol v1 contract (UI expects ~2s).
HEARTBEAT_INTERVAL_SECONDS = 2.0


def default_database_path() -> Path:
    """Resolve the default SQLite path: %LOCALAPPDATA%/Omni/omni.db.

    Falls back to the user's home directory when LOCALAPPDATA is unset
    (e.g. non-Windows CI runners), so the engine still has a writable,
    user-private location — never a world-readable shared directory.
    """
    local_app_data = os.environ.get("LOCALAPPDATA")
    base = Path(local_app_data) if local_app_data else Path.home() / ".local" / "share"
    return base / "Omni" / "omni.db"


class EngineSettings(BaseSettings):
    """Environment-driven configuration for one engine process.

    Reads (validated, fail-closed):
    - OMNI_ENGINE_PORT: TCP port for HTTP + WS (default 8765).
    - OMNI_DB_PATH: SQLite database file path (default %LOCALAPPDATA%/Omni/omni.db).
    """

    model_config = SettingsConfigDict(env_prefix="OMNI_", extra="ignore")

    # ge/le bounds: reject port 0 (ephemeral surprise) and out-of-range values.
    engine_port: int = Field(default=8765, ge=1, le=65535)
    db_path: Path = Field(default_factory=default_database_path)


def load_engine_settings() -> EngineSettings:
    """Load and validate settings from the environment.

    Raises pydantic ``ValidationError`` on malformed values — startup must
    fail closed rather than run on a guessed configuration.
    """
    return EngineSettings()
