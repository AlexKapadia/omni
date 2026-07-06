"""Builder for the `engine.heartbeat` event payload (WS protocol v1).

Purpose: one place that produces the pinned heartbeat shape —
``{"uptime_s": float, "engine_version": str, "python": str,
"stt_ready": bool}`` — so the server and future emitters cannot drift.
Pipeline position: consumed by ``engine.server``'s per-connection
heartbeat task, emitted every ~2 seconds to the UI.

No security-sensitive data crosses this boundary: the payload carries only
version/uptime facts, never paths, keys, or user content.
"""

import platform
import time
from typing import Any

from engine import ENGINE_VERSION


def build_heartbeat_payload(started_monotonic: float) -> dict[str, Any]:
    """Build one heartbeat payload.

    ``started_monotonic`` is the ``time.monotonic()`` reading captured at
    process start — monotonic (not wall) time, so uptime survives clock
    changes and is never negative.

    ``stt_ready`` is pinned ``False`` in M0: the STT stack does not exist
    yet, and the contract says the UI must be told honestly.
    """
    return {
        "uptime_s": time.monotonic() - started_monotonic,
        "engine_version": ENGINE_VERSION,
        "python": platform.python_version(),
        "stt_ready": False,
    }
