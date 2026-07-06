"""Silence auto-stop monitor: ends a capture session after sustained silence.

Purpose: the small, independently-testable timer behind M2's auto-stop —
polls the session's speech clock (``TranscriptEventEmitter``'s activity
timestamp) and, once silence has lasted the configured timeout, requests a
normal capture stop with ``reason="silence"``. Configured via the
``OMNI_AUTOSTOP_SILENCE_S`` environment variable (seconds; 0 disables).
Pipeline position: spawned by ``engine.stt.live_capture_service.start`` as
one of the session's background tasks; it never outlives the session.

Safety invariants:
- FAIL SAFE TOWARD CAPTURE: a malformed/negative/non-finite timeout value
  disables auto-stop (with a warning) rather than stopping a meeting the
  user did not ask to end — losing live capture is the harmful direction.
- The monitor requests the SAME stop path the user's command uses (flush,
  persist, broadcast); it never tears anything down itself, and a stop that
  raced a manual stop is logged and swallowed, never crashed on.
"""

import asyncio
import logging
import math
import os
import time
from collections.abc import Awaitable, Callable

logger = logging.getLogger(__name__)

# Env knob: silence seconds before auto-stop; unset/blank/0 = disabled.
AUTOSTOP_SILENCE_ENV_VAR = "OMNI_AUTOSTOP_SILENCE_S"

# How often the monitor re-checks between activity deadlines. The sleep is
# min(remaining, poll) so boundaries stay accurate to well under a second.
_POLL_INTERVAL_S = 1.0


def resolve_silence_timeout_s() -> float:
    """Parse ``OMNI_AUTOSTOP_SILENCE_S`` into a timeout, failing SAFE to 0.

    0 means disabled. Unparseable, negative, or non-finite values disable
    auto-stop with a warning — never guess a timeout, never stop a meeting
    on a config typo (the safe failure direction is "keep capturing").
    """
    raw = os.environ.get(AUTOSTOP_SILENCE_ENV_VAR, "").strip()
    if not raw:
        return 0.0
    try:
        value = float(raw)
    except ValueError:
        logger.warning("%s=%r is not a number; auto-stop disabled", AUTOSTOP_SILENCE_ENV_VAR, raw)
        return 0.0
    if not math.isfinite(value) or value < 0:
        logger.warning("%s=%r is invalid; auto-stop disabled", AUTOSTOP_SILENCE_ENV_VAR, raw)
        return 0.0
    return value


class SilenceAutoStopMonitor:
    """Watches one session's speech clock and requests a stop on timeout."""

    def __init__(
        self,
        timeout_s: float,
        last_activity_monotonic: Callable[[], float],
        request_stop: Callable[[], Awaitable[object]],
        now: Callable[[], float] = time.monotonic,
        poll_interval_s: float = _POLL_INTERVAL_S,
    ) -> None:
        self._timeout_s = timeout_s
        self._last_activity = last_activity_monotonic
        self._request_stop = request_stop
        self._now = now
        self._poll_interval_s = poll_interval_s

    async def run(self) -> None:
        """Poll until silence reaches the timeout, then request one stop.

        Boundary contract (tested to the second): silence strictly below the
        timeout never stops; silence at/over it does. Any speech pushes the
        deadline forward because the deadline derives from the activity
        clock, not from a countdown started at spawn.
        """
        while True:
            silent_for = self._now() - self._last_activity()
            remaining = self._timeout_s - silent_for
            if remaining <= 0:
                break
            await asyncio.sleep(min(remaining, self._poll_interval_s))
        try:
            # The normal stop path: flush pipelines, persist, broadcast
            # capture.stopped — identical to a user stop except the reason.
            await self._request_stop()
        except Exception as exc:  # a manual stop may have raced us — benign
            logger.warning("silence auto-stop could not stop capture: %s", exc)


def spawn_silence_auto_stop_tasks(
    timeout_s: float | None,
    last_activity_monotonic: Callable[[], float],
    request_stop: Callable[[], Awaitable[object]],
) -> list[asyncio.Task[None]]:
    """The capture service's one-liner: [monitor task], or [] when disabled.

    ``timeout_s=None`` reads the environment knob; explicit values (tests,
    future settings UI) win over the environment.
    """
    resolved = timeout_s if timeout_s is not None else resolve_silence_timeout_s()
    if resolved <= 0:  # disabled — no task, zero overhead
        return []
    monitor = SilenceAutoStopMonitor(resolved, last_activity_monotonic, request_stop)
    return [asyncio.create_task(monitor.run())]
