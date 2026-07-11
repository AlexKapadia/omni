"""Dictation session lifecycle: real pipeline, fake mic/models, honest text.

The REAL DictationSessionService drives real VAD gating, windowing and
merging with a scripted mic backend, an amplitude VAD, and a fake
transcriber — proving begin -> audio -> partial -> end -> verbatim text,
plus the fail-closed edges: double begin, end-without-begin,
release-before-speech, missing models, and the mic-only invariant.
"""

import asyncio
import time
from collections.abc import Callable
from pathlib import Path

import numpy as np
import numpy.typing as npt
import pytest

from engine.audio.audio_frame_types import StreamLabel
from engine.audio.dual_stream_capture_controller import CaptureDeviceSpec
from engine.dictation.dictation_session_service import (
    DictationSessionError,
    DictationSessionService,
)
from engine.stt.parakeet_nemo_transcriber import ParakeetNemoTranscriber
from engine.stt.word_token_types import WordToken


class FakeMicHandle:
    def __init__(self, on_chunk: Callable[[bytes, float], None]) -> None:
        self.on_chunk = on_chunk
        self.closed = False

    @property
    def is_alive(self) -> bool:
        return not self.closed

    def close(self) -> None:
        self.closed = True


class FakeMicBackend:
    """16 kHz mono mic so the resampler passes samples through exactly."""

    def __init__(self) -> None:
        self.probed_streams: list[StreamLabel] = []
        self.resolved_keys: list[str] = []
        self.opened_specs: list[CaptureDeviceSpec] = []
        self.handle: FakeMicHandle | None = None

    def probe_default_device(self, stream: StreamLabel) -> CaptureDeviceSpec:
        self.probed_streams.append(stream)
        return CaptureDeviceSpec(f"{stream.value}:Fake Mic", "Fake Mic", 16_000, 1)

    def resolve_input_device(self, key: str) -> CaptureDeviceSpec:
        self.resolved_keys.append(key)
        return CaptureDeviceSpec(key, key.split(":", 1)[-1], 16_000, 1)

    def open_capture_stream(
        self, spec: CaptureDeviceSpec, on_chunk: Callable[[bytes, float], None]
    ) -> FakeMicHandle:
        self.opened_specs.append(spec)
        self.handle = FakeMicHandle(on_chunk)
        return self.handle


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
        return [WordToken("buy", 0.1, 0.3), WordToken("milk", 0.4, 0.6)]


def amplitude_vad(chunk: npt.NDArray[np.float32]) -> float:
    return 0.99 if float(np.abs(chunk).mean()) > 0.01 else 0.01


def _active(service: DictationSessionService) -> bool:
    """Read is_active via a function boundary — mypy narrows member
    expressions and does not reset them across mutating awaits."""
    return service.is_active


def _make_service(
    backend: FakeMicBackend, partials: list[str] | None = None
) -> DictationSessionService:
    async def on_partial(text: str) -> None:
        if partials is not None:
            partials.append(text)

    return DictationSessionService(
        backend_factory=lambda: backend,
        transcriber=FakeLoadedTranscriber(),
        vad_factory=lambda: amplitude_vad,
        on_partial_text=on_partial,
    )


def _push_speech(handle: FakeMicHandle, seconds: float, t_cursor: float) -> float:
    """Push 0.1 s int16 speech chunks through the driver callback."""
    for _ in range(round(seconds / 0.1)):
        chunk = (np.full(1600, 0.5, dtype=np.float32) * 32767).astype(np.int16)
        t_cursor += 0.1
        handle.on_chunk(chunk.tobytes(), t_cursor)
    return t_cursor


async def test_begin_speak_end_returns_verbatim_text_and_partials() -> None:
    backend = FakeMicBackend()
    partials: list[str] = []
    service = _make_service(backend, partials)

    await service.begin()
    assert _active(service)
    assert backend.handle is not None
    _push_speech(backend.handle, 1.0, time.monotonic())
    await asyncio.sleep(0.15)  # let the drain loop pump at least once

    text = await service.end()

    assert text == "buy milk"  # verbatim join, nothing rewritten
    assert not _active(service)
    assert backend.handle.closed  # mic released on end (no lingering capture)
    # end() may have raced ahead of a slow window; but with our synchronous
    # tail drain the final MUST have flowed through the partial channel too.
    assert partials, "partials must stream while dictating"
    assert partials[-1] == "buy milk"


async def test_mic_only_invariant_never_probes_loopback() -> None:
    """Dictation is the user's voice — the loopback (other people) must
    never be opened by this service (least-capture)."""
    backend = FakeMicBackend()
    service = _make_service(backend)
    await service.begin()
    await service.end()
    assert backend.probed_streams == [StreamLabel.ME]


async def test_preferred_mic_key_uses_resolve_not_default_probe() -> None:
    """When mic_device_id is configured, open that device — not the default."""
    backend = FakeMicBackend()
    service = _make_service(backend)
    service.configure("parakeet", preferred_me_device_key="9:USB Mic")
    await service.begin()
    await service.end()
    assert backend.resolved_keys == ["9:USB Mic"]
    assert backend.probed_streams == []
    assert backend.opened_specs[0].key == "9:USB Mic"


async def test_release_before_speech_returns_empty_text() -> None:
    backend = FakeMicBackend()
    service = _make_service(backend)
    await service.begin()
    text = await service.end()  # released instantly, nothing said
    assert text == ""


async def test_double_begin_is_refused() -> None:
    backend = FakeMicBackend()
    service = _make_service(backend)
    await service.begin()
    with pytest.raises(DictationSessionError, match="already running"):
        await service.begin()
    await service.end()


async def test_end_without_begin_is_refused() -> None:
    service = _make_service(FakeMicBackend())
    with pytest.raises(DictationSessionError, match="not running"):
        await service.end()


async def test_session_is_reusable_after_end() -> None:
    """Hold -> release -> hold again: state must reset completely, and the
    second session must not leak the first session's words."""
    backend = FakeMicBackend()
    service = _make_service(backend)

    await service.begin()
    assert backend.handle is not None
    _push_speech(backend.handle, 0.6, time.monotonic())
    first = await service.end()

    await service.begin()
    second = await service.end()  # silent second hold

    assert first == "buy milk"
    assert second == ""  # no bleed-through from session one


async def test_cancel_is_idempotent_and_tears_down() -> None:
    backend = FakeMicBackend()
    service = _make_service(backend)
    await service.begin()
    await service.cancel()
    assert not _active(service)
    await service.cancel()  # second cancel: no-op, no raise


async def test_missing_vad_model_fails_closed(tmp_path: Path) -> None:
    """No models -> a loud refusal, never a silently-deaf session."""
    service = DictationSessionService(
        backend_factory=FakeMicBackend,
        models_dir=tmp_path,  # empty: no silero_vad.onnx here
        transcriber=FakeLoadedTranscriber(),
    )
    with pytest.raises(DictationSessionError, match="VAD model missing"):
        await service.begin()
    assert not _active(service)


async def test_mic_open_failure_fails_closed_and_resets() -> None:
    class BrokenBackend(FakeMicBackend):
        def open_capture_stream(
            self, spec: CaptureDeviceSpec, on_chunk: Callable[[bytes, float], None]
        ) -> FakeMicHandle:
            raise OSError("device vanished")

    service = _make_service(BrokenBackend())
    with pytest.raises(DictationSessionError, match="could not open microphone"):
        await service.begin()
    assert not _active(service)  # torn down: a retry can start clean
