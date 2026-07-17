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
- The monitor re-reads its timeout each loop (env getter or callable) so a
  mid-session ``settings.update`` that writes ``OMNI_AUTOSTOP_SILENCE_S``
  takes effect; timeout 0 disables without tearing the session down.
- The monitor requests the SAME stop path the user's command uses (flush,
  persist, broadcast); it never tears anything down itself, and a stop that
  raced a manual stop is logged and swallowed, never crashed on.
"""

from __future__ import annotations

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

TimeoutGetter = Callable[[], float]


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
        timeout_s: float | TimeoutGetter,
        last_activity_monotonic: Callable[[], float],
        request_stop: Callable[[], Awaitable[object]],
        now: Callable[[], float] = time.monotonic,
        poll_interval_s: float = _POLL_INTERVAL_S,
    ) -> None:
        # Callable form lets settings.update → env take effect mid-session.
        self._timeout_s: TimeoutGetter = (
            timeout_s if callable(timeout_s) else (lambda: float(timeout_s))
        )
        self._last_activity = last_activity_monotonic
        self._request_stop = request_stop
        self._now = now
        self._poll_interval_s = poll_interval_s

    async def run(self) -> None:
        """Poll until silence reaches the timeout, then request one stop.

        Boundary contract (tested to the second): silence strictly below the
        timeout never stops; silence at/over it does. Any speech pushes the
        deadline forward because the deadline derives from the activity
        clock, not from a countdown started at spawn. Timeout 0 (or a
        mid-session disable) keeps polling without stopping.
        """
        while True:
            timeout = self._timeout_s()
            if timeout <= 0:
                # Disabled — keep looping so a later re-enable still works.
                await asyncio.sleep(self._poll_interval_s)
                continue
            silent_for = self._now() - self._last_activity()
            remaining = timeout - silent_for
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

    ``timeout_s=None`` reads the environment knob each loop (so a mid-session
    settings.update that writes the env takes effect). Explicit values
    (tests, injected service knobs) are fixed for the session lifetime.
    """
    if timeout_s is not None:
        if timeout_s <= 0:  # disabled — no task, zero overhead
            return []

        def getter() -> float:
            return float(timeout_s)
    else:
        if resolve_silence_timeout_s() <= 0:
            return []
        getter = resolve_silence_timeout_s
    monitor = SilenceAutoStopMonitor(getter, last_activity_monotonic, request_stop)
    return [asyncio.create_task(monitor.run())]
