"""LiveCaptureService: concurrent start/stop races under the lifecycle lock.

Two concurrent start() calls must produce exactly one meeting; concurrent
stop() must not double-run teardown.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from pathlib import Path

import numpy as np
import numpy.typing as npt

from engine.audio.audio_frame_types import StreamLabel
from engine.audio.dual_stream_capture_controller import CaptureDeviceSpec
from engine.protocol import EventBroadcastHub
from engine.stt.capture_model_loading import CaptureServiceError
from engine.stt.live_capture_service import LiveCaptureService
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
        self.open_count = 0

    def probe_default_device(self, stream: StreamLabel) -> CaptureDeviceSpec:
        name = "Loopback" if stream is StreamLabel.THEM else "Microphone"
        return CaptureDeviceSpec(f"{stream.value}:{name}", name, 16_000, 1)

    def resolve_input_device(self, key: str) -> CaptureDeviceSpec:
        return CaptureDeviceSpec(key, key.split(":", 1)[-1], 16_000, 1)

    def open_capture_stream(
        self, spec: CaptureDeviceSpec, on_chunk: Callable[[bytes, float], None]
    ) -> _FakeStreamHandle:
        self.open_count += 1
        label = StreamLabel.THEM if "Loopback" in spec.name else StreamLabel.ME
        handle = _FakeStreamHandle(on_chunk)
        self.handles[label] = handle
        return handle


class _FakeLoadedTranscriber(ParakeetNemoTranscriber):
    def __init__(self) -> None:
        super().__init__(model_path=Path("unused.nemo"))

    @property
    def is_loaded(self) -> bool:
        return True

    def load(self) -> None:
        return

    def transcribe_window(self, samples: npt.NDArray[np.float32]) -> list[WordToken]:
        return [WordToken("hi", 0.0, 0.1)]


def _amplitude_vad(chunk: npt.NDArray[np.float32]) -> float:
    return 0.01


def _make_service(
    tmp_db_path: Path, real_migrations_dir: Path
) -> tuple[LiveCaptureService, _FakeBackend]:
    hub = EventBroadcastHub()
    backend = _FakeBackend()
    service = LiveCaptureService(
        db_path=tmp_db_path,
        migrations_dir=real_migrations_dir,
        hub=hub,
        backend_factory=lambda: backend,
        models_dir=Path("unused-models-dir"),
        transcriber=_FakeLoadedTranscriber(),
        vad_factory=lambda: _amplitude_vad,
    )
    return service, backend


async def test_concurrent_starts_produce_exactly_one_meeting(
    tmp_db_path: Path, real_migrations_dir: Path
) -> None:
    service, backend = _make_service(tmp_db_path, real_migrations_dir)
    results = await asyncio.gather(
        service.start("A"),
        service.start("B"),
        return_exceptions=True,
    )
    successes = [r for r in results if isinstance(r, str)]
    failures = [r for r in results if isinstance(r, BaseException)]
    assert len(successes) == 1
    assert len(failures) == 1
    assert isinstance(failures[0], CaptureServiceError)
    assert "already running" in str(failures[0])
    # One session = two streams (them + me), not four.
    assert backend.open_count == 2
    assert service.is_capturing
    await service.stop()


async def test_concurrent_stops_only_one_succeeds(
    tmp_db_path: Path, real_migrations_dir: Path
) -> None:
    service, _backend = _make_service(tmp_db_path, real_migrations_dir)
    meeting_id = await service.start("Race stop")
    results = await asyncio.gather(
        service.stop(),
        service.stop(),
        return_exceptions=True,
    )
    successes = [r for r in results if isinstance(r, str)]
    failures = [r for r in results if isinstance(r, BaseException)]
    assert successes == [meeting_id]
    assert len(failures) == 1
    assert isinstance(failures[0], CaptureServiceError)
    assert "not running" in str(failures[0])
    assert not service.is_capturing
