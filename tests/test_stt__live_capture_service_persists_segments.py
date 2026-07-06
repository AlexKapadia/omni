"""Live capture service integration: real pipelines + DB, fake hardware/models.

The REAL LiveCaptureService drives real VAD gating, windowing, merging,
persistence, and event broadcast — with a scripted capture backend, an
amplitude VAD, and a fake transcriber. Proves capture.start -> audio ->
transcript.final -> transcript_segments row -> capture.stop, end to end,
with honest lag numbers, on a throwaway database.
"""

import asyncio
import time
from collections.abc import Callable
from pathlib import Path

import aiosqlite
import numpy as np
import numpy.typing as npt
import pytest

from engine.audio.audio_frame_types import StreamLabel
from engine.audio.dual_stream_capture_controller import CaptureDeviceSpec
from engine.protocol import Envelope, EventBroadcastHub
from engine.stt.capture_model_loading import CaptureServiceError
from engine.stt.live_capture_service import LiveCaptureService
from engine.stt.parakeet_nemo_transcriber import ParakeetNemoTranscriber
from engine.stt.word_token_types import WordToken


class FakeStreamHandle:
    def __init__(self, spec: CaptureDeviceSpec, on_chunk: Callable[[bytes, float], None]) -> None:
        self.spec = spec
        self.on_chunk = on_chunk
        self.closed = False

    @property
    def is_alive(self) -> bool:
        return not self.closed

    def close(self) -> None:
        self.closed = True


class FakeBackend:
    """16 kHz mono devices so the resampler passes samples through exactly."""

    def __init__(self) -> None:
        self.handles: dict[StreamLabel, FakeStreamHandle] = {}

    def probe_default_device(self, stream: StreamLabel) -> CaptureDeviceSpec:
        name = "Loopback" if stream is StreamLabel.THEM else "Microphone"
        return CaptureDeviceSpec(f"{stream.value}:{name}", name, 16_000, 1)

    def open_capture_stream(
        self, spec: CaptureDeviceSpec, on_chunk: Callable[[bytes, float], None]
    ) -> FakeStreamHandle:
        label = StreamLabel.THEM if "Loopback" in spec.name else StreamLabel.ME
        handle = FakeStreamHandle(spec, on_chunk)
        self.handles[label] = handle
        return handle


class FakeLoadedTranscriber(ParakeetNemoTranscriber):
    """Duck-typed stand-in: 'loaded' from birth, deterministic words."""

    def __init__(self) -> None:
        super().__init__(model_path=Path("unused.nemo"))
        self._loaded = True

    @property
    def is_loaded(self) -> bool:
        return True

    def load(self) -> None:  # Never touches nemo/torch.
        return

    def transcribe_window(self, samples: npt.NDArray[np.float32]) -> list[WordToken]:
        duration = samples.size / 16_000
        return [
            WordToken("hello", max(0.0, duration - 1.0), max(0.05, duration - 0.85)),
            WordToken("wörld", max(0.05, duration - 0.8), max(0.1, duration - 0.6)),
        ]


def amplitude_vad(chunk: npt.NDArray[np.float32]) -> float:
    return 0.99 if float(np.abs(chunk).mean()) > 0.01 else 0.01


def service_flags(service: LiveCaptureService) -> tuple[bool, bool]:
    """(stt_ready, capturing) via a function boundary — mypy narrows member
    expressions and does not reset them across mutating awaits."""
    return service.is_stt_ready, service.is_capturing


class EventLog:
    def __init__(self, hub: EventBroadcastHub) -> None:
        self.events: list[Envelope] = []
        hub.subscribe(self._collect)

    async def _collect(self, envelope: Envelope) -> None:
        self.events.append(envelope)

    def named(self, name: str) -> list[Envelope]:
        return [e for e in self.events if e.name == name]


async def _wait_until(predicate: Callable[[], bool], timeout_s: float = 5.0) -> None:
    deadline = asyncio.get_running_loop().time() + timeout_s
    while asyncio.get_running_loop().time() < deadline:
        if predicate():
            return
        await asyncio.sleep(0.02)
    raise AssertionError("condition not reached in time")


def _push_audio(
    handle: FakeStreamHandle, seconds: float, amplitude: float, t_cursor: float
) -> float:
    """Push 0.1 s int16 chunks through the driver callback; returns new cursor."""
    for _ in range(round(seconds / 0.1)):
        chunk = (np.full(1600, amplitude, dtype=np.float32) * 32767).astype(np.int16)
        t_cursor += 0.1
        handle.on_chunk(chunk.tobytes(), t_cursor)
    return t_cursor


def make_service(
    tmp_db_path: Path, real_migrations_dir: Path
) -> tuple[LiveCaptureService, FakeBackend, EventLog]:
    hub = EventBroadcastHub()
    backend = FakeBackend()
    service = LiveCaptureService(
        db_path=tmp_db_path,
        migrations_dir=real_migrations_dir,
        hub=hub,
        backend_factory=lambda: backend,
        models_dir=Path("unused-models-dir"),
        transcriber=FakeLoadedTranscriber(),
        vad_factory=lambda: amplitude_vad,
    )
    return service, backend, EventLog(hub)


async def test_full_session_persists_verbatim_segments_and_emits_events(
    tmp_db_path: Path, real_migrations_dir: Path
) -> None:
    service, backend, log = make_service(tmp_db_path, real_migrations_dir)
    assert service_flags(service) == (False, False)  # Honest before load.

    meeting_id = await service.start("Weekly sync")
    assert service_flags(service) == (True, True)
    assert len(log.named("capture.started")) == 1
    assert log.named("capture.started")[0].payload == {
        "meeting_id": meeting_id,
        "reason": "command",
    }

    # 2 s of speech then 1 s of silence into the LOOPBACK ("them") stream.
    t = time.monotonic()
    t = _push_audio(backend.handles[StreamLabel.THEM], 2.0, 0.5, t)
    _push_audio(backend.handles[StreamLabel.THEM], 1.0, 0.0, t)
    await _wait_until(lambda: bool(log.named("transcript.final")))

    stopped_id = await service.stop()
    assert stopped_id == meeting_id and not service.is_capturing
    assert len(log.named("capture.stopped")) == 1

    # --- the WS event carries the pinned final shape with honest numbers.
    final = log.named("transcript.final")[0].payload
    assert final["stream"] == "them"
    assert final["text"] == "hello wörld"  # Verbatim tokens, space-joined.
    assert final["lag_ms"] >= 0.0
    assert final["t_end"] > final["t_start"] >= 0.0
    assert isinstance(final["seq"], int) and final["seq"] >= 1
    partials = log.named("transcript.partial")
    assert partials and partials[0].payload["stream"] == "them"

    # --- the DB row matches the event exactly (persistence fidelity).
    connection = await aiosqlite.connect(tmp_db_path)
    try:
        cursor = await connection.execute(
            "SELECT id, meeting_id, stream, text, t_start, t_end FROM transcript_segments"
        )
        rows = list(await cursor.fetchall())
        await cursor.close()
        assert len(rows) == 1
        segment_id, row_meeting, stream, text, t_start, t_end = tuple(rows[0])
        assert segment_id == final["segment_id"]
        assert row_meeting == meeting_id
        assert stream == "them" and text == "hello wörld"
        assert (t_start, t_end) == (final["t_start"], final["t_end"])

        cursor = await connection.execute(
            "SELECT title, ended_at FROM meetings WHERE id = ?", (meeting_id,)
        )
        meeting = await cursor.fetchone()
        await cursor.close()
        assert meeting is not None
        assert meeting[0] == "Weekly sync"
        assert meeting[1] is not None  # ended_at stamped by stop().
    finally:
        await connection.close()


async def test_mic_stream_segments_are_labelled_me(
    tmp_db_path: Path, real_migrations_dir: Path
) -> None:
    service, backend, log = make_service(tmp_db_path, real_migrations_dir)
    await service.start(None)
    t = time.monotonic()
    t = _push_audio(backend.handles[StreamLabel.ME], 1.5, 0.4, t)
    _push_audio(backend.handles[StreamLabel.ME], 1.0, 0.0, t)
    await _wait_until(lambda: bool(log.named("transcript.final")))
    await service.stop()
    assert log.named("transcript.final")[0].payload["stream"] == "me"


async def test_double_start_and_idle_stop_fail_closed(
    tmp_db_path: Path, real_migrations_dir: Path
) -> None:
    service, _backend, _log = make_service(tmp_db_path, real_migrations_dir)
    with pytest.raises(CaptureServiceError, match="not running"):
        await service.stop()
    await service.start(None)
    with pytest.raises(CaptureServiceError, match="already running"):
        await service.start(None)
    await service.stop()
    # A fresh session can start after a clean stop (state fully reset).
    second = await service.start("Round two")
    assert isinstance(second, str)
    await service.stop()


async def test_stop_finalises_an_utterance_still_in_progress(
    tmp_db_path: Path, real_migrations_dir: Path
) -> None:
    """User hits stop mid-sentence: the open segment must still land in
    the DB (flush-on-stop), not vanish."""
    service, backend, log = make_service(tmp_db_path, real_migrations_dir)
    meeting_id = await service.start(None)
    t = time.monotonic()
    _push_audio(backend.handles[StreamLabel.THEM], 1.5, 0.5, t)  # No closing silence.
    # Let the drain loop ingest everything before stopping.
    await asyncio.sleep(0.3)
    await service.stop()
    finals = log.named("transcript.final")
    assert len(finals) == 1
    connection = await aiosqlite.connect(tmp_db_path)
    try:
        cursor = await connection.execute(
            "SELECT COUNT(*) FROM transcript_segments WHERE meeting_id = ?", (meeting_id,)
        )
        row = await cursor.fetchone()
        await cursor.close()
        assert row is not None and row[0] == 1
    finally:
        await connection.close()


def test_models_missing_fails_closed_with_a_clear_reason(
    tmp_db_path: Path, real_migrations_dir: Path, tmp_path: Path
) -> None:
    """No VAD model on disk and no injected fakes: start must refuse."""

    async def run() -> None:
        service = LiveCaptureService(
            db_path=tmp_db_path,
            migrations_dir=real_migrations_dir,
            hub=EventBroadcastHub(),
            models_dir=tmp_path / "empty-models",
        )
        with pytest.raises(CaptureServiceError, match="VAD model missing"):
            await service.start(None)
        assert not service.is_stt_ready  # Still honest after the failure.

    asyncio.run(run())
