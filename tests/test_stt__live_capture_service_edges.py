"""LiveCaptureService orchestration edges: crash logging, preload, teardown.

Real service, fake hardware/models. Covers the branches the happy-path
integration test misses: the background-task crash callback, preload
swallowing a loader failure (stt stays honestly not-ready), start() tearing
down its connection and failing closed when capture cannot open, the
device-changed broadcast, the periodic stats loop, and keep-audio being
written during drain and finalised on stop.
"""

import asyncio
import contextlib
import time
from collections.abc import Callable
from pathlib import Path

import numpy as np
import numpy.typing as npt
import pytest

from engine.audio.audio_frame_types import StreamLabel
from engine.audio.dual_stream_capture_controller import CaptureDeviceSpec
from engine.protocol import Envelope, EventBroadcastHub
from engine.stt import live_capture_service as lcs_module
from engine.stt.capture_model_loading import CaptureServiceError
from engine.stt.live_capture_service import LiveCaptureService, _log_task_crash
from engine.stt.parakeet_nemo_transcriber import ParakeetNemoTranscriber
from engine.stt.word_token_types import WordToken


class _FakeStreamHandle:
    def __init__(self, on_chunk: Callable[[bytes, float], None]) -> None:
        self.on_chunk = on_chunk
        self.closed = False

    @property
    def is_alive(self) -> bool:
        return not self.closed

    def close(self) -> None:
        self.closed = True


class _FakeBackend:
    def __init__(self) -> None:
        self.handles: dict[StreamLabel, _FakeStreamHandle] = {}

    def probe_default_device(self, stream: StreamLabel) -> CaptureDeviceSpec:
        name = "Loopback" if stream is StreamLabel.THEM else "Microphone"
        return CaptureDeviceSpec(f"{stream.value}:{name}", name, 16_000, 1)

    def open_capture_stream(
        self, spec: CaptureDeviceSpec, on_chunk: Callable[[bytes, float], None]
    ) -> _FakeStreamHandle:
        label = StreamLabel.THEM if "Loopback" in spec.name else StreamLabel.ME
        handle = _FakeStreamHandle(on_chunk)
        self.handles[label] = handle
        return handle


class _FailingBackend(_FakeBackend):
    def open_capture_stream(
        self, spec: CaptureDeviceSpec, on_chunk: Callable[[bytes, float], None]
    ) -> _FakeStreamHandle:
        raise RuntimeError("no audio device")


class _FakeLoadedTranscriber(ParakeetNemoTranscriber):
    def __init__(self) -> None:
        super().__init__(model_path=Path("unused.nemo"))

    @property
    def is_loaded(self) -> bool:
        return True

    def load(self) -> None:
        return

    def transcribe_window(self, samples: npt.NDArray[np.float32]) -> list[WordToken]:
        duration = samples.size / 16_000
        return [WordToken("hi", max(0.0, duration - 0.5), max(0.01, duration - 0.4))]


def _amplitude_vad(chunk: npt.NDArray[np.float32]) -> float:
    return 0.99 if float(np.abs(chunk).mean()) > 0.01 else 0.01


class _EventLog:
    def __init__(self, hub: EventBroadcastHub) -> None:
        self.events: list[Envelope] = []
        hub.subscribe(self._collect)

    async def _collect(self, envelope: Envelope) -> None:
        self.events.append(envelope)

    def named(self, name: str) -> list[Envelope]:
        return [e for e in self.events if e.name == name]


def _make_service(
    tmp_db_path: Path,
    real_migrations_dir: Path,
    *,
    backend: _FakeBackend | None = None,
) -> tuple[LiveCaptureService, _FakeBackend, _EventLog]:
    hub = EventBroadcastHub()
    backend = backend if backend is not None else _FakeBackend()
    service = LiveCaptureService(
        db_path=tmp_db_path,
        migrations_dir=real_migrations_dir,
        hub=hub,
        backend_factory=lambda: backend,
        models_dir=Path("unused-models-dir"),
        transcriber=_FakeLoadedTranscriber(),
        vad_factory=lambda: _amplitude_vad,
    )
    return service, backend, _EventLog(hub)


def _push_audio(
    handle: _FakeStreamHandle, seconds: float, amplitude: float, t_cursor: float
) -> float:
    for _ in range(round(seconds / 0.1)):
        chunk = (np.full(1600, amplitude, dtype=np.float32) * 32767).astype(np.int16)
        t_cursor += 0.1
        handle.on_chunk(chunk.tobytes(), t_cursor)
    return t_cursor


def _has_recorder(service: LiveCaptureService) -> bool:
    """Read the keep-audio recorder slot through a function boundary so mypy
    does not persist member narrowing across mutating awaits."""
    return service._keep_audio_recorder is not None


async def _wait_until(predicate: Callable[[], bool], timeout_s: float = 5.0) -> None:
    deadline = asyncio.get_running_loop().time() + timeout_s
    while asyncio.get_running_loop().time() < deadline:
        if predicate():
            return
        await asyncio.sleep(0.02)
    raise AssertionError("condition not reached in time")


# --------------------------------------------------------------------------- #
# _log_task_crash
# --------------------------------------------------------------------------- #


async def test_log_task_crash_reports_exception(
    caplog: pytest.LogCaptureFixture,
) -> None:
    async def _boom() -> None:
        raise ValueError("pump exploded")

    task: asyncio.Task[None] = asyncio.create_task(_boom())
    with contextlib.suppress(ValueError):
        await task
    with caplog.at_level("ERROR"):
        _log_task_crash(task)
    assert "background task crashed" in caplog.text


async def test_log_task_crash_ignores_cancelled_task(
    caplog: pytest.LogCaptureFixture,
) -> None:
    async def _sleep() -> None:
        await asyncio.sleep(10)

    task: asyncio.Task[None] = asyncio.create_task(_sleep())
    await asyncio.sleep(0)  # let it start
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task
    with caplog.at_level("ERROR"):
        _log_task_crash(task)  # cancelled -> must NOT log a crash
    assert "background task crashed" not in caplog.text


# --------------------------------------------------------------------------- #
# preload_models — swallows loader failure, stays honestly not-ready
# --------------------------------------------------------------------------- #


async def test_preload_swallows_failure_and_stays_not_ready(
    tmp_db_path: Path, real_migrations_dir: Path, caplog: pytest.LogCaptureFixture
) -> None:
    service, _backend, _log = _make_service(tmp_db_path, real_migrations_dir)

    async def _boom() -> None:
        raise RuntimeError("weights corrupt")

    service._models.ensure_loaded = _boom  # type: ignore[method-assign]
    with caplog.at_level("ERROR"):
        await service.preload_models()  # must NOT raise
    assert service.is_stt_ready is False  # honest: never claimed ready
    assert "preload failed" in caplog.text


# --------------------------------------------------------------------------- #
# start() — fail closed and clean up when capture cannot open
# --------------------------------------------------------------------------- #


async def test_start_fails_closed_and_releases_connection(
    tmp_db_path: Path, real_migrations_dir: Path
) -> None:
    service, _backend, log = _make_service(
        tmp_db_path, real_migrations_dir, backend=_FailingBackend()
    )
    with pytest.raises(CaptureServiceError, match="could not start capture"):
        await service.start(None)
    # Fail closed: no session state leaks, no started event emitted.
    assert service.is_capturing is False
    assert service._connection is None
    assert log.named("capture.started") == []
    # And a later, healthy start still works (state was fully released).
    healthy, _b, _l = _make_service(tmp_db_path, real_migrations_dir)
    meeting_id = await healthy.start(None)
    assert isinstance(meeting_id, str)
    await healthy.stop()


# --------------------------------------------------------------------------- #
# _on_device_changed — announces recovery to the UI
# --------------------------------------------------------------------------- #


async def test_on_device_changed_broadcasts_event(
    tmp_db_path: Path, real_migrations_dir: Path
) -> None:
    service, _backend, log = _make_service(tmp_db_path, real_migrations_dir)
    service._on_device_changed(StreamLabel.THEM, "New Speakers", 123.5)
    await _wait_until(lambda: bool(log.named("capture.device_changed")))
    payload = log.named("capture.device_changed")[0].payload
    assert payload["device_name"] == "New Speakers"
    assert payload["recovered_ms"] == 123.5


# --------------------------------------------------------------------------- #
# _stats_loop — periodic latency summary while a session runs
# --------------------------------------------------------------------------- #


async def test_stats_loop_logs_latency_summary(
    tmp_db_path: Path, real_migrations_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(lcs_module, "STATS_LOG_INTERVAL_S", 0.01)  # fast beat
    service, _backend, _log = _make_service(tmp_db_path, real_migrations_dir)
    await service.start(None)
    try:
        calls = {"n": 0}
        emitter = service._emitter
        assert emitter is not None
        monkeypatch.setattr(
            emitter, "log_latency_summary", lambda: calls.__setitem__("n", calls["n"] + 1)
        )
        await _wait_until(lambda: calls["n"] >= 1)  # stats loop fired at least once
    finally:
        await service.stop()


# --------------------------------------------------------------------------- #
# keep-audio: written during drain, finalised on stop
# --------------------------------------------------------------------------- #


async def test_keep_audio_written_during_session_and_closed_on_stop(
    tmp_db_path: Path, real_migrations_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import wave

    from engine.storage.app_settings_repository import SETTING_KEEP_AUDIO, write_setting
    from engine.storage.sqlite_connection import open_sqlite_connection
    from engine.storage.sqlite_migrations_runner import apply_migrations

    # Persist the explicit opt-in BEFORE the session opens its own connection.
    await apply_migrations(tmp_db_path, real_migrations_dir)
    setup = await open_sqlite_connection(tmp_db_path)
    try:
        await write_setting(setup, SETTING_KEEP_AUDIO, True)
    finally:
        await setup.close()

    audio_dir = tmp_path / "kept-audio"
    monkeypatch.setenv("OMNI_AUDIO_DIR", str(audio_dir))

    service, backend, _log = _make_service(tmp_db_path, real_migrations_dir)
    meeting_id = await service.start(None)
    # Via a function boundary so mypy does not persist member narrowing across
    # the mutating stop() await below (matches the sibling integration test).
    assert _has_recorder(service) is True  # opt-in honoured

    t = time.monotonic()
    _push_audio(backend.handles[StreamLabel.ME], 1.0, 0.5, t)
    await _wait_until(lambda: (audio_dir / meeting_id / "me.wav").is_file())
    await service.stop()

    # Finalised on stop: recorder released and a real, playable WAV on disk.
    assert _has_recorder(service) is False
    me_wav = audio_dir / meeting_id / "me.wav"
    with wave.open(str(me_wav), "rb") as handle:
        assert handle.getnchannels() == 1
        assert handle.getsampwidth() == 2
        assert handle.getnframes() > 0  # frames actually landed via the drain loop
