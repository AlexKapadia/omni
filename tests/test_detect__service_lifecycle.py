"""Detection service lifecycle: deterministic ticks, idempotent start/stop,
no leaked tasks, and a poll loop that survives broken decision consumers.

Uses a fake AsyncClock whose sleep blocks on test-released permits, so every
tick is explicit and the suite never depends on wall-clock timing.
"""

import asyncio

import pytest

from engine.detect.auto_start_rules_engine import AutoStartRulesEngine
from engine.detect.detection_service import DetectionService
from engine.detect.detection_signal_types import (
    SOURCE_ADHOC_LOOPBACK,
    SOURCE_TEAMS,
    SOURCE_ZOOM,
    DesktopSnapshot,
    DetectionDecision,
    SuggestCapture,
    WindowInfo,
)
from engine.detect.meeting_process_watcher import MeetingProcessWatcher
from engine.detect.microphone_in_use_detector import ConsentStoreEntry, MicrophoneInUseDetector
from engine.detect.sustained_loopback_vad_trigger import (
    SustainedLoopbackVadConfig,
    SustainedLoopbackVadTrigger,
)


class FakeClock:
    """Deterministic AsyncClock: sleep() blocks until the test permits a tick."""

    def __init__(self) -> None:
        self.time = 0.0
        self._permits = asyncio.Semaphore(0)

    def monotonic(self) -> float:
        return self.time

    async def sleep(self, seconds: float) -> None:
        await self._permits.acquire()
        self.time += seconds

    def allow_tick(self) -> None:
        self._permits.release()


class ScriptedDesktop:
    """Mutable snapshot source the test can point at different window titles."""

    def __init__(self) -> None:
        self.titles: list[str] = []

    def snapshot(self) -> DesktopSnapshot:
        return DesktopSnapshot(
            processes=(),
            windows=tuple(WindowInfo(pid=1, title=t) for t in self.titles),
        )


def empty_consent_store() -> list[ConsentStoreEntry]:
    return []


async def drain_event_loop(cycles: int = 10) -> None:
    for _ in range(cycles):
        await asyncio.sleep(0)


def build_service(
    desktop: ScriptedDesktop,
    clock: FakeClock,
    decisions: list[DetectionDecision],
    capture_active_flag: dict[str, bool],
    on_decision_error_once: bool = False,
) -> DetectionService:
    state = {"raised": False}

    def on_decision(decision: DetectionDecision) -> None:
        if on_decision_error_once and not state["raised"]:
            state["raised"] = True
            raise RuntimeError("consumer exploded")
        decisions.append(decision)

    return DetectionService(
        process_watcher=MeetingProcessWatcher(desktop.snapshot),
        microphone_detector=MicrophoneInUseDetector(empty_consent_store),
        vad_trigger=SustainedLoopbackVadTrigger(
            SustainedLoopbackVadConfig(min_speech_s_in_window=1.0, rearm_below_speech_s=0.5)
        ),
        rules_engine=AutoStartRulesEngine(),
        is_capture_active=lambda: capture_active_flag["active"],
        on_decision=on_decision,
        clock=clock,
        poll_interval_s=3.0,
    )


async def test_rearm_for_ui_re_emits_active_meeting_immediately() -> None:
    """After the one-shot suggest, reconnecting UI must toast again without waiting."""
    desktop = ScriptedDesktop()
    desktop.titles = ["Zoom Meeting"]
    clock = FakeClock()
    decisions: list[DetectionDecision] = []
    service = build_service(desktop, clock, decisions, {"active": False})
    service.start()
    await drain_event_loop()
    assert len(decisions) == 1
    service.rearm_suggestions_for_ui()
    assert len(decisions) == 2
    assert isinstance(decisions[1], SuggestCapture)
    assert decisions[1].source == SOURCE_ZOOM
    await service.stop()

    desktop = ScriptedDesktop()
    desktop.titles = ["Zoom Meeting"]
    clock = FakeClock()
    rearm_decisions: list[DetectionDecision] = []
    service = build_service(desktop, clock, rearm_decisions, {"active": False})

    baseline_tasks = len(asyncio.all_tasks())
    service.start()
    # WHY locals: mypy narrows the property EXPRESSION and would mark the
    # post-stop assertion unreachable; snapshotting sidesteps that.
    running_after_start = service.is_running
    assert running_after_start
    await drain_event_loop()  # first tick runs immediately on start
    assert len(rearm_decisions) == 1
    assert isinstance(rearm_decisions[0], SuggestCapture)
    assert rearm_decisions[0].source == SOURCE_ZOOM

    clock.allow_tick()
    await drain_event_loop()  # second tick: same session -> no duplicate
    assert len(rearm_decisions) == 1

    await service.stop()
    running_after_stop = service.is_running
    assert not running_after_stop
    assert len(asyncio.all_tasks()) == baseline_tasks  # no leaked tasks


async def test_start_is_idempotent_single_loop_task() -> None:
    desktop = ScriptedDesktop()
    clock = FakeClock()
    service = build_service(desktop, clock, [], {"active": False})
    baseline_tasks = len(asyncio.all_tasks())
    service.start()
    first_count = len(asyncio.all_tasks())
    service.start()  # second start while running: no-op
    service.start()
    assert len(asyncio.all_tasks()) == first_count == baseline_tasks + 1
    await service.stop()
    assert len(asyncio.all_tasks()) == baseline_tasks


async def test_stop_is_idempotent_and_safe_before_start() -> None:
    desktop = ScriptedDesktop()
    clock = FakeClock()
    service = build_service(desktop, clock, [], {"active": False})
    await service.stop()  # never started: must be a no-op
    service.start()
    await drain_event_loop()
    await service.stop()
    await service.stop()  # double stop: no-op
    assert not service.is_running


async def test_restart_after_stop_works() -> None:
    desktop = ScriptedDesktop()
    desktop.titles = ["Zoom Meeting"]
    clock = FakeClock()
    decisions: list[DetectionDecision] = []
    service = build_service(desktop, clock, decisions, {"active": False})
    service.start()
    await drain_event_loop()
    await service.stop()
    count_after_first_run = len(decisions)
    service.start()  # restart: a fresh loop task must come up
    assert service.is_running
    await drain_event_loop()
    await service.stop()
    assert len(decisions) == count_after_first_run  # same session: still deduped


async def test_broken_on_decision_consumer_does_not_kill_the_loop() -> None:
    desktop = ScriptedDesktop()
    desktop.titles = ["Zoom Meeting"]
    clock = FakeClock()
    decisions: list[DetectionDecision] = []
    service = build_service(
        desktop, clock, decisions, {"active": False}, on_decision_error_once=True
    )
    service.start()
    await drain_event_loop()  # first decision hits the raising consumer
    assert decisions == []  # swallowed by the consumer's failure

    desktop.titles = ["Meeting with Alex | Microsoft Teams"]  # a NEW source appears
    clock.allow_tick()
    await drain_event_loop()  # loop must still be alive and deliver it
    assert len(decisions) == 1
    assert isinstance(decisions[0], SuggestCapture)
    assert decisions[0].source == SOURCE_TEAMS
    await service.stop()


async def test_vad_feed_surfaces_adhoc_suggestion_on_next_tick() -> None:
    desktop = ScriptedDesktop()
    clock = FakeClock()
    decisions: list[DetectionDecision] = []
    service = build_service(desktop, clock, decisions, {"active": False})
    # 1.5s of sustained speech >= the 1.0s test threshold -> event queued.
    for i in range(4):
        service.feed_vad_sample(i * 0.5, 0.9)
    service.start()
    await drain_event_loop()
    assert len(decisions) == 1
    assert isinstance(decisions[0], SuggestCapture)
    assert decisions[0].source == SOURCE_ADHOC_LOOPBACK
    await service.stop()


async def test_capture_active_keeps_everything_quiet() -> None:
    desktop = ScriptedDesktop()
    desktop.titles = ["Zoom Meeting"]
    clock = FakeClock()
    decisions: list[DetectionDecision] = []
    service = build_service(desktop, clock, decisions, {"active": True})
    for i in range(4):  # VAD trigger must also stay quiet while capturing
        service.feed_vad_sample(i * 0.5, 0.9)
    service.start()
    await drain_event_loop()
    clock.allow_tick()
    await drain_event_loop()
    assert decisions == []
    await service.stop()


def test_rejects_nonpositive_poll_interval() -> None:
    desktop = ScriptedDesktop()
    with pytest.raises(ValueError):
        DetectionService(
            process_watcher=MeetingProcessWatcher(desktop.snapshot),
            microphone_detector=MicrophoneInUseDetector(empty_consent_store),
            vad_trigger=SustainedLoopbackVadTrigger(),
            rules_engine=AutoStartRulesEngine(),
            is_capture_active=lambda: False,
            on_decision=lambda _decision: None,
            poll_interval_s=0.0,
        )
