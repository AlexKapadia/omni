"""Silence auto-stop: env parsing fail-safe, boundary-exact timing, speech resets.

The monitor's contract, tested to the second with a controllable clock:
silence strictly under the timeout never stops (N-1), silence at/over it
does (N+1), and ANY speech pushes the deadline forward. The env knob fails
SAFE — a config typo disables auto-stop rather than ending a meeting the
user did not ask to end. The service-level test proves the critical
non-deadlock property: the monitor task calling ``stop()`` completes the
FULL teardown (session reset, capture.stopped reason='silence') even though
stop() cancels the session's task list the monitor itself rides in.
"""

import asyncio
import time
from pathlib import Path

import pytest

from engine.stt.silence_auto_stop_monitor import (
    AUTOSTOP_SILENCE_ENV_VAR,
    SilenceAutoStopMonitor,
    resolve_silence_timeout_s,
    spawn_silence_auto_stop_tasks,
)
from tests.test_stt__live_capture_service_persists_segments import make_service


# ------------------------------------------------------------- env parsing
@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("90", 90.0),
        ("2.5", 2.5),
        ("0", 0.0),  # explicit disable
        ("", 0.0),  # blank disables
        ("  ", 0.0),
        ("ninety", 0.0),  # fail SAFE: typo disables, never guesses
        ("-5", 0.0),  # negative disables
        ("inf", 0.0),  # non-finite disables
        ("nan", 0.0),
    ],
)
def test_env_knob_parses_fail_safe(
    raw: str, expected: float, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(AUTOSTOP_SILENCE_ENV_VAR, raw)
    assert resolve_silence_timeout_s() == expected


def test_env_knob_unset_means_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(AUTOSTOP_SILENCE_ENV_VAR, raising=False)
    assert resolve_silence_timeout_s() == 0.0


async def test_spawn_returns_no_task_when_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(AUTOSTOP_SILENCE_ENV_VAR, raising=False)

    async def never() -> None:
        raise AssertionError("must not be called")

    assert spawn_silence_auto_stop_tasks(None, time.monotonic, never) == []
    assert spawn_silence_auto_stop_tasks(0.0, time.monotonic, never) == []


async def test_explicit_timeout_wins_over_the_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(AUTOSTOP_SILENCE_ENV_VAR, "9999")
    stopped = asyncio.Event()

    async def request_stop() -> None:
        stopped.set()

    clock = FakeClock(0.0)
    tasks = spawn_silence_auto_stop_tasks(9999.0, lambda: clock.value - 10_000, request_stop)
    try:
        # last activity is 10 000 s ago vs a 9 999 s timeout: fires at once.
        await asyncio.wait_for(stopped.wait(), timeout=2.0)
    finally:
        for task in tasks:
            task.cancel()


# -------------------------------------------------------- boundary timing
class FakeClock:
    """A controllable monotonic clock (real asyncio sleeps stay tiny)."""

    def __init__(self, value: float) -> None:
        self.value = value

    def now(self) -> float:
        return self.value


def make_monitor(
    timeout_s: float, clock: FakeClock, last_activity: FakeClock
) -> tuple[SilenceAutoStopMonitor, asyncio.Event]:
    stopped = asyncio.Event()

    async def request_stop() -> None:
        stopped.set()

    monitor = SilenceAutoStopMonitor(
        timeout_s,
        last_activity.now,
        request_stop,
        now=clock.now,
        poll_interval_s=0.001,  # fast polling so tests are quick AND exact
    )
    return monitor, stopped


async def test_silence_one_second_under_the_timeout_never_stops() -> None:
    clock, activity = FakeClock(0.0), FakeClock(0.0)
    monitor, stopped = make_monitor(10.0, clock, activity)
    task = asyncio.create_task(monitor.run())
    try:
        clock.value = 9.0  # N-1: strictly under the boundary
        await asyncio.sleep(0.05)  # many poll cycles at this clock value
        assert not stopped.is_set()
    finally:
        task.cancel()


async def test_silence_reaching_the_timeout_stops_exactly_once() -> None:
    clock, activity = FakeClock(0.0), FakeClock(0.0)
    monitor, stopped = make_monitor(10.0, clock, activity)
    task = asyncio.create_task(monitor.run())
    clock.value = 11.0  # N+1: over the boundary
    await asyncio.wait_for(stopped.wait(), timeout=2.0)
    await asyncio.wait_for(task, timeout=2.0)  # the monitor exits after firing


async def test_speech_resets_the_deadline() -> None:
    clock, activity = FakeClock(0.0), FakeClock(0.0)
    monitor, stopped = make_monitor(10.0, clock, activity)
    task = asyncio.create_task(monitor.run())
    try:
        clock.value = 9.5
        activity.value = 9.0  # speech at t=9: only 0.5 s of silence now
        await asyncio.sleep(0.05)
        assert not stopped.is_set()
        clock.value = 18.9  # 9.9 s after the last speech: still under
        await asyncio.sleep(0.05)
        assert not stopped.is_set()
        clock.value = 19.1  # 10.1 s after the last speech: over
        await asyncio.wait_for(stopped.wait(), timeout=2.0)
    finally:
        task.cancel()


async def test_a_racing_manual_stop_is_swallowed_not_crashed() -> None:
    clock, activity = FakeClock(100.0), FakeClock(0.0)

    async def already_stopped() -> None:
        raise RuntimeError("capture is not running")

    monitor = SilenceAutoStopMonitor(
        10.0, activity.now, already_stopped, now=clock.now, poll_interval_s=0.001
    )
    await asyncio.wait_for(monitor.run(), timeout=2.0)  # completes without raising


async def test_monitor_re_reads_timeout_each_loop_so_mid_session_change_applies() -> None:
    """settings.update that writes OMNI_AUTOSTOP_SILENCE_S must take effect live."""
    clock, activity = FakeClock(0.0), FakeClock(0.0)
    timeout_box = {"value": 10.0}
    stopped = asyncio.Event()

    async def request_stop() -> None:
        stopped.set()

    monitor = SilenceAutoStopMonitor(
        lambda: timeout_box["value"],
        activity.now,
        request_stop,
        now=clock.now,
        poll_interval_s=0.001,
    )
    task = asyncio.create_task(monitor.run())
    try:
        clock.value = 9.5
        await asyncio.sleep(0.03)
        assert not stopped.is_set()
        timeout_box["value"] = 5.0  # mid-session shorten
        clock.value = 6.0  # 6s silence vs new 5s timeout → fire
        await asyncio.wait_for(stopped.wait(), timeout=2.0)
    finally:
        task.cancel()


async def test_monitor_disables_when_timeout_becomes_zero_mid_session() -> None:
    clock, activity = FakeClock(0.0), FakeClock(0.0)
    timeout_box = {"value": 5.0}
    stopped = asyncio.Event()

    async def request_stop() -> None:
        stopped.set()

    monitor = SilenceAutoStopMonitor(
        lambda: timeout_box["value"],
        activity.now,
        request_stop,
        now=clock.now,
        poll_interval_s=0.001,
    )
    task = asyncio.create_task(monitor.run())
    try:
        clock.value = 3.0
        await asyncio.sleep(0.02)
        timeout_box["value"] = 0.0  # settings.update → disable
        clock.value = 100.0  # would have fired under the old 5s timeout
        await asyncio.sleep(0.05)
        assert not stopped.is_set()
    finally:
        task.cancel()


async def test_spawn_with_none_re_reads_env_so_disable_takes_effect(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(AUTOSTOP_SILENCE_ENV_VAR, "9999")
    stopped = asyncio.Event()

    async def request_stop() -> None:
        stopped.set()

    # Fresh activity clock: silence is ~0 under the initial 9999s timeout.
    activity_at = time.monotonic()
    tasks = spawn_silence_auto_stop_tasks(None, lambda: activity_at, request_stop)
    assert len(tasks) == 1
    try:
        monkeypatch.setenv(AUTOSTOP_SILENCE_ENV_VAR, "0")  # mid-session disable via settings
        await asyncio.sleep(0.1)
        assert not stopped.is_set()
    finally:
        for task in tasks:
            task.cancel()


# -------------------------------------------------- service-level teardown
async def test_service_auto_stop_completes_full_teardown_with_reason_silence(
    tmp_db_path: Path, real_migrations_dir: Path
) -> None:
    """The deadlock hunt: the monitor task itself calls service.stop(),
    which cancels the session's tasks — including, naively, the monitor.
    The stop must still finish: state reset, DB closed, event broadcast."""
    service, _backend, log = make_service(tmp_db_path, real_migrations_dir)
    service._silence_timeout_s = 0.3  # inject a fast timeout for the test

    def capturing() -> bool:
        # Function boundary: mypy narrows member expressions and would
        # otherwise flag the post-loop assert as unreachable.
        return service.is_capturing

    meeting_id = await service.start("Silent meeting")
    assert capturing()

    deadline = asyncio.get_running_loop().time() + 5.0
    while capturing() and asyncio.get_running_loop().time() < deadline:
        await asyncio.sleep(0.02)

    assert not capturing()  # teardown COMPLETED (no deadlock)
    stopped = log.named("capture.stopped")
    assert len(stopped) == 1
    assert stopped[0].payload == {"meeting_id": meeting_id, "reason": "silence"}
    # The session is fully reusable afterwards (state was really reset).
    second = await service.start("Round two")
    await service.stop()
    assert isinstance(second, str)
