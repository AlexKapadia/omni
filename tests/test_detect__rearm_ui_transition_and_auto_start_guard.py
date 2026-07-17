"""Rearm: 0→1 UI only; auto-start sources never resurrect after manual stop."""

from __future__ import annotations

import asyncio

from engine.detect.auto_start_rules_engine import AutoStartRulesEngine, DetectionRuleSettings
from engine.detect.detection_service import DetectionService
from engine.detect.detection_signal_types import (
    SOURCE_ZOOM,
    AutoStart,
    DesktopSnapshot,
    DetectionDecision,
    MeetingAppDetected,
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
    def __init__(self) -> None:
        self.time = 0.0
        self._permits = asyncio.Semaphore(0)

    def monotonic(self) -> float:
        return self.time

    async def sleep(self, seconds: float) -> None:
        await self._permits.acquire()
        self.time += seconds


class ScriptedDesktop:
    def __init__(self) -> None:
        self.titles: list[str] = ["Zoom Meeting"]

    def snapshot(self) -> DesktopSnapshot:
        return DesktopSnapshot(
            processes=(),
            windows=tuple(WindowInfo(pid=1, title=t) for t in self.titles),
        )


def empty_consent() -> list[ConsentStoreEntry]:
    return []


async def drain(cycles: int = 10) -> None:
    for _ in range(cycles):
        await asyncio.sleep(0)


def mad(source: str, confidence: float) -> MeetingAppDetected:
    return MeetingAppDetected(
        source=source,
        app=f"{source}.exe",
        window_title_hint=None,
        confidence=confidence,
        evidence="window_title",
    )


def test_rearm_excludes_auto_start_eligible_sources() -> None:
    """After AutoStart + handled, rearm must not clear auto-start sources."""
    settings = DetectionRuleSettings(auto_start_sources=frozenset({SOURCE_ZOOM}))
    engine = AutoStartRulesEngine(settings)
    decisions = engine.update(0.0, [mad(SOURCE_ZOOM, 0.9)], False)
    assert len(decisions) == 1
    assert isinstance(decisions[0], AutoStart)

    engine.rearm_suggestions_for_ui(1.0)
    # Still handled: no second AutoStart on the next tick.
    assert engine.update(2.0, [mad(SOURCE_ZOOM, 0.9)], False) == []


def test_rearm_still_clears_suggest_only_sources() -> None:
    """Non-auto-start sources still rearm so a reconnect can toast again."""
    engine = AutoStartRulesEngine()  # auto_start_sources empty
    decisions = engine.update(0.0, [mad(SOURCE_ZOOM, 0.9)], False)
    assert isinstance(decisions[0], SuggestCapture)
    engine.rearm_suggestions_for_ui(1.0)
    again = engine.update(2.0, [mad(SOURCE_ZOOM, 0.9)], False)
    assert len(again) == 1
    assert isinstance(again[0], SuggestCapture)


def test_manual_stop_then_rearm_does_not_auto_restart() -> None:
    """Capture covers the session; rearm after stop must not AutoStart again."""
    settings = DetectionRuleSettings(auto_start_sources=frozenset({SOURCE_ZOOM}))
    engine = AutoStartRulesEngine(settings)
    assert isinstance(engine.update(0.0, [mad(SOURCE_ZOOM, 0.9)], False)[0], AutoStart)
    # User's capture runs, then they stop while Zoom is still open.
    engine.update(10.0, [mad(SOURCE_ZOOM, 0.9)], capture_active=True)
    assert engine.update(20.0, [mad(SOURCE_ZOOM, 0.9)], capture_active=False) == []
    engine.rearm_suggestions_for_ui(21.0)
    assert engine.update(22.0, [mad(SOURCE_ZOOM, 0.9)], capture_active=False) == []


async def test_reconnect_does_not_duplicate_meeting_detected() -> None:
    """Second UI connect (1→2) must not rearm / re-emit meeting.detected."""
    desktop = ScriptedDesktop()
    clock = FakeClock()
    decisions: list[DetectionDecision] = []
    service = DetectionService(
        process_watcher=MeetingProcessWatcher(desktop.snapshot),
        microphone_detector=MicrophoneInUseDetector(empty_consent),
        vad_trigger=SustainedLoopbackVadTrigger(
            SustainedLoopbackVadConfig(min_speech_s_in_window=1.0, rearm_below_speech_s=0.5)
        ),
        rules_engine=AutoStartRulesEngine(),
        is_capture_active=lambda: False,
        on_decision=decisions.append,
        clock=clock,
        poll_interval_s=3.0,
    )
    service.start()
    await drain()
    assert len(decisions) == 1  # first poll: SuggestCapture

    service.notify_ui_connected()  # 0→1: rearm + immediate tick
    assert len(decisions) == 2

    service.notify_ui_connected()  # 1→2: no rearm
    assert len(decisions) == 2

    service.notify_ui_disconnected()
    service.notify_ui_disconnected()  # back to 0
    service.notify_ui_connected()  # 0→1 again: rearm once more
    assert len(decisions) == 3
    await service.stop()
