"""Detection composition root: lifecycle, poll loop, and the wiring surface.

Purpose: owns the async polling loop that drives the detectors and the rules
engine, and exposes the ONLY two integration points the server needs:

- ``on_decision`` callback — every ``DetectionDecision`` the rules engine
  emits is delivered here. The wiring pass (orchestrator-owned, deferred)
  maps decisions to WS events on the existing broadcast hub:
      SuggestCapture -> ``meeting.detected``      {source, reason, confidence}
      AutoStart      -> ``meeting.detected``      {source, reason, confidence,
                                                   auto_start: true}
      SuggestStop    -> ``capture.suggest_stop``  {reason}
- ``feed_vad_sample(sample_ts_s, speech_probability)`` — the loopback
  Silero-VAD feed. The wiring pass calls this with per-chunk speech
  probabilities from the LOOPBACK stream's VAD (the same probabilities that
  already flow into ``engine.stt.vad_gating_state_machine``); no new audio
  path is created. Must be called from the engine's event-loop thread.

Pipeline position: server startup constructs this service (with the real
snapshot provider, winreg reader, and system clock) and calls ``start()``;
``stop()`` runs on shutdown. Tests inject fakes for all of it.

Security/compliance invariants:
- Observation only: this service can at most raise SUGGESTION decisions;
  execution (actually starting capture) stays behind the server's existing
  approval-carded command path (approval-before-execute).
- Fail closed, never crash: detector errors already degrade to "no
  signals"; a failing ``on_decision`` callback or rules-engine bug is
  logged and the loop continues — detection must never take the engine down.
- Lifecycle is idempotent and leak-free: double start is a no-op, stop
  cancels and awaits the loop task (no orphaned tasks).
"""

import asyncio
import logging
import time
from collections.abc import Callable
from typing import Protocol

from engine.detect.auto_start_rules_engine import AutoStartRulesEngine, DetectionRuleSettings
from engine.detect.detection_signal_types import DetectionDecision, DetectionSignal
from engine.detect.meeting_process_watcher import MeetingProcessWatcher
from engine.detect.microphone_in_use_detector import MicrophoneInUseDetector
from engine.detect.sustained_loopback_vad_trigger import SustainedLoopbackVadTrigger

logger = logging.getLogger(__name__)


class AsyncClock(Protocol):
    """Injected time source so tests drive the loop deterministically."""

    def monotonic(self) -> float:
        """Current monotonic time in seconds."""
        ...

    async def sleep(self, seconds: float) -> None:
        """Suspend the loop until the next tick."""
        ...


class SystemClock:
    """Production clock: ``time.monotonic`` + ``asyncio.sleep``."""

    def monotonic(self) -> float:
        return time.monotonic()

    async def sleep(self, seconds: float) -> None:
        await asyncio.sleep(seconds)


class DetectionService:
    """Start/stop lifecycle around one poll loop (see module docstring)."""

    def __init__(
        self,
        process_watcher: MeetingProcessWatcher,
        microphone_detector: MicrophoneInUseDetector,
        vad_trigger: SustainedLoopbackVadTrigger,
        rules_engine: AutoStartRulesEngine,
        is_capture_active: Callable[[], bool],
        on_decision: Callable[[DetectionDecision], None],
        clock: AsyncClock | None = None,
        poll_interval_s: float = 3.0,
    ) -> None:
        if poll_interval_s <= 0:
            raise ValueError("poll_interval_s must be > 0")
        self._process_watcher = process_watcher
        self._microphone_detector = microphone_detector
        self._vad_trigger = vad_trigger
        self._rules_engine = rules_engine
        self._is_capture_active = is_capture_active
        self._on_decision = on_decision
        self._clock: AsyncClock = clock if clock is not None else SystemClock()
        self._poll_interval_s = poll_interval_s
        self._task: asyncio.Task[None] | None = None
        # VAD events raised between ticks, drained into the next tick's signals.
        self._pending_vad_signals: list[DetectionSignal] = []

    @property
    def is_running(self) -> bool:
        return self._task is not None and not self._task.done()

    def feed_vad_sample(self, sample_ts_s: float, speech_probability: float) -> None:
        """Ingest one loopback-VAD sample (wiring surface, event-loop thread)."""
        event = self._vad_trigger.feed(
            sample_ts_s, speech_probability, capture_active=self._is_capture_active()
        )
        if event is not None:
            self._pending_vad_signals.append(event)

    def dismiss_suggestion(self, dedupe_key: str) -> None:
        """Wiring surface for the UI's 'dismiss' action on a suggestion card."""
        self._rules_engine.dismiss(dedupe_key, self._clock.monotonic())

    def apply_detection_settings(self, settings: DetectionRuleSettings) -> None:
        """Hot-reload user knobs without restarting the poll loop."""
        self._rules_engine.apply_settings(settings)

    def start(self) -> None:
        """Begin polling. Idempotent: a second start while running is a no-op."""
        if self.is_running:
            return
        self._task = asyncio.get_running_loop().create_task(
            self._run_loop(), name="detection-service-poll-loop"
        )

    async def stop(self) -> None:
        """Cancel and await the loop task. Idempotent; leaves no orphan task."""
        task, self._task = self._task, None
        if task is None or task.done():
            return
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            # Expected: our own cancellation completing. Re-raise if the
            # CALLER is being cancelled so outer cancellation still works.
            if (current := asyncio.current_task()) is not None and current.cancelled():
                raise  # pragma: no cover — outer-cancellation passthrough

    async def _run_loop(self) -> None:
        while True:
            self._tick()
            await self._clock.sleep(self._poll_interval_s)

    def _tick(self) -> None:
        """One poll: gather signals -> rules engine -> deliver decisions."""
        try:
            signals: list[DetectionSignal] = []
            signals.extend(self._process_watcher.poll_once())
            signals.extend(self._microphone_detector.poll_once())
            signals.extend(self._pending_vad_signals)
            self._pending_vad_signals.clear()
            decisions = self._rules_engine.update(
                now_s=self._clock.monotonic(),
                signals=signals,
                capture_active=self._is_capture_active(),
            )
        except Exception:
            # Fail closed, never crash: a detection bug must not take the
            # engine down — skip this tick and keep polling.
            logger.exception("detection tick failed; skipping this poll")
            return
        for decision in decisions:
            try:
                self._on_decision(decision)
            except Exception:
                # A broken consumer must not kill detection for later ticks.
                logger.exception("on_decision callback failed for %r", decision)
