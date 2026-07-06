"""Shared pytest fixtures for the engine test suite.

All database fixtures use ``tmp_path`` — tests never touch the real
%LOCALAPPDATA% database (synthetic-fixtures-only rule), and no test opens
a network socket (the WS tests run in-process via Starlette's TestClient).
"""

import json
from pathlib import Path
from typing import Any

import pytest
from starlette.testclient import WebSocketTestSession

# Repo root, derived from this file so tests run from any CWD.
REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture()
def real_migrations_dir() -> Path:
    """The repository's real migrations directory — tests the real artifact."""
    return REPO_ROOT / "migrations"


@pytest.fixture()
def tmp_db_path(tmp_path: Path) -> Path:
    """A throwaway SQLite path; never the user's real database."""
    return tmp_path / "omni-test.db"


def receive_frame(ws: WebSocketTestSession) -> dict[str, Any]:
    """Receive one frame and decode it, asserting it is a JSON object."""
    decoded = json.loads(ws.receive_text())
    assert isinstance(decoded, dict), f"frame is not a JSON object: {decoded!r}"
    return decoded


def receive_non_heartbeat_frame(ws: WebSocketTestSession, limit: int = 10) -> dict[str, Any]:
    """Receive frames, skipping heartbeats, until a reply/event of interest.

    WHY: the per-connection heartbeat task may interleave beats with
    replies, so tests must tolerate (and skip) them deterministically.
    A hard limit keeps a broken server from hanging the suite.
    """
    for _ in range(limit):
        frame = receive_frame(ws)
        if frame.get("name") != "engine.heartbeat":
            return frame
    raise AssertionError(f"no non-heartbeat frame within {limit} frames")
