"""Dictation session error/edge branches not covered by the lifecycle suite.

Targets the uncovered seams of ``DictationSessionService``:
- the synchronous TAIL drain on ``end()`` (frames the pump had not reached
  yet must still be transcribed — the utterance tail is never lost);
- the audio-callback error paths (a torn/empty chunk is dropped, never
  crashing the callback thread nor corrupting the transcript);
- ``_ensure_models_loaded`` branches: default-VAD-factory install when a
  real model file exists, the fail-closed "STT deps missing" refusal, and
  the transcriber build + load path;
- the default backend factory returns the real hardware backend object.

All model/mic/STT boundaries are faked or monkeypatched — no torch, no
NeMo, no real microphone (no-network / no-hardware unit-test rule).
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
    _default_backend_factory,
)
from engine.stt.model_weights_downloader import PARAKEET_FILENAME, SILERO_VAD_FILENAME
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
    """16 kHz mono mic: the resampler runs in passthrough so int16 speech
    survives sample-exact and torn/empty chunks hit the callback guards."""

    def __init__(self) -> None:
        self.handle: FakeMicHandle | None = None

    def probe_default_device(self, stream: StreamLabel) -> CaptureDeviceSpec:
        return CaptureDeviceSpec(f"{stream.value}:Fake Mic", "Fake Mic", 16_000, 1)

    def resolve_input_device(self, key: str) -> CaptureDeviceSpec:
        return CaptureDeviceSpec(key, key.split(":", 1)[-1], 16_000, 1)

    def open_capture_stream(
        self, spec: CaptureDeviceSpec, on_chunk: Callable[[bytes, float], None]
    ) -> FakeMicHandle:
        self.handle = FakeMicHandle(on_chunk)
        return self.handle


class FakeLoadedTranscriber(ParakeetNemoTranscriber):
    """Loaded-from-birth stand-in emitting deterministic words."""

    def __init__(self) -> None:
        super().__init__(model_path=Path("unused.nemo"))

    @property
    def is_loaded(self) -> bool:
        return True

    def load(self) -> None:
        return

    def transcribe_window(self, samples: npt.NDArray[np.float32]) -> list[WordToken]:
        return [WordToken("buy", 0.1, 0.3), WordToken("milk", 0.4, 0.6)]


def amplitude_vad(chunk: npt.NDArray[np.float32]) -> float:
    return 0.99 if float(np.abs(chunk).mean()) > 0.01 else 0.01


def _make_service(backend: FakeMicBackend) -> DictationSessionService:
    return DictationSessionService(
        backend_factory=lambda: backend,
        transcriber=FakeLoadedTranscriber(),
        vad_factory=lambda: amplitude_vad,
    )


def _speech_chunk() -> bytes:
    return (np.full(1600, 0.5, dtype=np.float32) * 32767).astype(np.int16).tobytes()


# ---------------------------------------------------------------------------
# The synchronous tail drain on end()
# ---------------------------------------------------------------------------


async def test_end_transcribes_the_tail_frames_the_pump_had_not_reached() -> None:
    """Frames appended AFTER the drain loop parked (mid 50 ms sleep) are still
    picked up by end()'s synchronous tail drain -> the utterance tail is
    never dropped. Deterministic: we push only once the loop is asleep."""
    backend = FakeMicBackend()
    service = _make_service(backend)
    await service.begin()
    assert backend.handle is not None
    # Yield once so the drain loop runs its first (empty) pass and parks in
    # its 50 ms sleep before we enqueue any audio.
    await asyncio.sleep(0)
    t = time.monotonic()
    for _ in range(10):  # ~1 s of speech, all queued during the sleep window
        t += 0.1
        backend.handle.on_chunk(_speech_chunk(), t)
    text = await service.end()  # completes well within the 50 ms window
    assert text == "buy milk"  # tail frames flowed through the pipeline
    assert backend.handle.closed


# ---------------------------------------------------------------------------
# Audio-callback error branches: torn and empty chunks
# ---------------------------------------------------------------------------


async def test_torn_and_empty_chunks_are_dropped_not_crashed() -> None:
    """A malformed (odd-length -> unaligned int16) chunk and an empty chunk
    are both swallowed by the callback: no frame is produced, no exception
    escapes, and a subsequent real chunk still transcribes cleanly."""
    backend = FakeMicBackend()
    service = _make_service(backend)
    await service.begin()
    assert backend.handle is not None
    await asyncio.sleep(0)
    t = time.monotonic()
    # Odd byte count: np.frombuffer(int16) raises ValueError -> dropped (215-217).
    backend.handle.on_chunk(b"\x01\x02\x03", t + 0.1)
    # Empty payload: resampler returns zero samples -> early return (219).
    backend.handle.on_chunk(b"", t + 0.2)
    text_after_noise_only = await service.end()
    assert text_after_noise_only == ""  # nothing transcribable survived

    # And the session recovers: real speech after the noise transcribes.
    await service.begin()
    assert backend.handle is not None
    await asyncio.sleep(0)
    t2 = time.monotonic()
    backend.handle.on_chunk(b"\x01", t2 + 0.1)  # torn again
    for _ in range(8):
        t2 += 0.1
        backend.handle.on_chunk(_speech_chunk(), t2)
    text = await service.end()
    assert text == "buy milk"


# ---------------------------------------------------------------------------
# _ensure_models_loaded branches
# ---------------------------------------------------------------------------


async def test_default_vad_factory_installed_when_model_file_present(
    tmp_path: Path,
) -> None:
    """vad_factory is None + the silero file exists on disk -> a default
    factory is installed (the missing-file branch is NOT taken)."""
    (tmp_path / SILERO_VAD_FILENAME).write_bytes(b"onnx-model-bytes")
    service = DictationSessionService(
        backend_factory=FakeMicBackend,
        models_dir=tmp_path,
        transcriber=FakeLoadedTranscriber(),  # skip the transcriber-build path
        vad_factory=None,  # force the default-VAD-factory branch
    )
    await service._ensure_models_loaded()
    assert service._vad_factory is not None  # a factory was installed
    assert service._models_ready is True


async def test_missing_stt_dependencies_fail_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No injected transcriber + the heavy STT stack absent -> a loud refusal,
    never a silently-deaf session."""
    from engine.stt import live_transcriber_factory

    monkeypatch.setattr(live_transcriber_factory, "stt_dependencies_available", lambda: False)
    service = DictationSessionService(
        backend_factory=FakeMicBackend,
        models_dir=tmp_path,
        transcriber=None,  # force the build path
        vad_factory=lambda: amplitude_vad,  # skip the VAD-file branch
    )
    with pytest.raises(DictationSessionError, match="STT dependencies not installed"):
        await service._ensure_models_loaded()
    assert service._models_ready is False  # never flips ready on failure


async def test_transcriber_is_built_and_loaded_when_deps_available(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """deps available + no injected transcriber -> the service constructs a
    transcriber at the parakeet path and loads it off the event loop."""
    from engine.stt import live_transcriber_factory

    class FakeBuiltTranscriber:
        def __init__(self, model_path: Path) -> None:
            self.model_path = model_path
            self._loaded = False
            self.load_calls = 0
            built_instances.append(self)

        @property
        def is_loaded(self) -> bool:
            return self._loaded

        def load(self) -> None:
            self.load_calls += 1
            self._loaded = True

    built_instances: list[FakeBuiltTranscriber] = []

    monkeypatch.setattr(live_transcriber_factory, "stt_dependencies_available", lambda: True)
    monkeypatch.setattr(live_transcriber_factory, "ParakeetNemoTranscriber", FakeBuiltTranscriber)
    # Default settings path: no db → parakeet (legacy inject-free unit path).
    service = DictationSessionService(
        backend_factory=FakeMicBackend,
        models_dir=tmp_path,
        transcriber=None,
        vad_factory=lambda: amplitude_vad,
        stt_engine="parakeet",
    )
    await service._ensure_models_loaded()
    assert len(built_instances) == 1  # built exactly once
    built = built_instances[0]
    assert built.model_path == tmp_path / PARAKEET_FILENAME  # built at the exact path
    assert built.load_calls == 1 and built.is_loaded  # loaded exactly once
    assert service._models_ready is True


async def test_dictation_builds_openai_compatible_from_settings(
    tmp_path: Path,
) -> None:
    """Cloud STT setting must build OpenAiCompatible, never hardcode Parakeet."""
    from engine.stt.openai_compatible_stt import OpenAiCompatibleSttBackend

    service = DictationSessionService(
        backend_factory=FakeMicBackend,
        models_dir=tmp_path,
        transcriber=None,
        vad_factory=lambda: amplitude_vad,
        stt_engine="openai_compatible",
        stt_model_id="whisper-1",
        openai_base_url="https://api.openai.com/v1",
        openai_api_key="sk-test",
    )
    await service._ensure_models_loaded()
    assert isinstance(service._transcriber, OpenAiCompatibleSttBackend)
    assert service._models_ready is True


async def test_dictation_openai_compatible_fails_closed_without_key(
    tmp_path: Path,
) -> None:
    service = DictationSessionService(
        backend_factory=FakeMicBackend,
        models_dir=tmp_path,
        transcriber=None,
        vad_factory=lambda: amplitude_vad,
        stt_engine="openai_compatible",
        stt_model_id="whisper-1",
        openai_base_url="https://api.openai.com/v1",
        openai_api_key=None,
    )
    with pytest.raises(DictationSessionError, match=r"openai_compatible|API key"):
        await service._ensure_models_loaded()
    assert service._models_ready is False


async def test_ensure_models_loaded_is_idempotent(tmp_path: Path) -> None:
    """A second call after ready returns immediately (the early-return guard),
    never rebuilding models."""
    service = _make_service(FakeMicBackend())
    await service._ensure_models_loaded()
    first = service._transcriber
    await service._ensure_models_loaded()
    assert service._transcriber is first  # unchanged; no rebuild


# ---------------------------------------------------------------------------
# The default backend factory (real hardware backend, inert construction)
# ---------------------------------------------------------------------------


def test_default_backend_factory_returns_a_probeable_backend() -> None:
    """Construction is inert (no PyAudio init until probe): we get a real
    backend object exposing the CaptureBackend surface."""
    backend = _default_backend_factory()
    assert hasattr(backend, "probe_default_device")
    assert hasattr(backend, "open_capture_stream")
