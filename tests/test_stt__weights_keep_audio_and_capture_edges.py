"""Remaining error/edge branches: weights fetcher, keep-audio, model loader.

No network, no GPU: the HTTPS fetcher's streaming loop is exercised against a
FAKE urlopen; keep-audio directory resolution and fail-soft close are driven
directly; the capture model loader's fail-closed paths are asserted with a
missing VAD file, absent STT deps, and a (monkeypatched) deps-present path
that still fails closed on the absent Parakeet checkpoint.
"""

import sys
import types
from pathlib import Path
from typing import Any

import pytest

from engine.stt import keep_audio_recorder
from engine.stt.capture_model_loading import CaptureModelLoader, CaptureServiceError
from engine.stt.keep_audio_recorder import KeepAudioRecorder, keep_audio_directory
from engine.stt.model_weights_downloader import (
    SILERO_VAD_FILENAME,
    _https_fetch,
    _print_progress,
    default_manifest_path,
    load_pinned_sha256_by_filename,
)

# --------------------------------------------------------------------------- #
# _https_fetch — scheme guard + streaming loop (fake urlopen, no network)
# --------------------------------------------------------------------------- #


class _FakeResponse:
    def __init__(self, chunks: list[bytes], content_length: str | None) -> None:
        self._chunks = list(chunks)
        self.headers: dict[str, str] = {}
        if content_length is not None:
            self.headers["Content-Length"] = content_length

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, *exc: Any) -> None:
        return None

    def read(self, size: int) -> bytes:
        return self._chunks.pop(0) if self._chunks else b""


def test_https_fetch_rejects_non_https(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="refusing non-HTTPS"):
        _https_fetch("http://insecure.test/x", tmp_path / "out.bin", lambda d, t: None)


def test_https_fetch_streams_bytes_and_reports_progress(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    chunks = [b"aaaa", b"bbb", b"c"]  # 8 bytes total
    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda request: _FakeResponse(chunks, "8"),
    )
    beats: list[tuple[int, int | None]] = []
    dest = tmp_path / "out.bin"
    _https_fetch("https://ok.test/x", dest, lambda done, total: beats.append((done, total)))
    assert dest.read_bytes() == b"aaaabbbc"  # every chunk written, in order
    assert beats == [(4, 8), (7, 8), (8, 8)]  # cumulative done, known total


def test_https_fetch_handles_missing_content_length(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda request: _FakeResponse([b"zz"], None),  # no Content-Length header
    )
    beats: list[tuple[int, int | None]] = []
    dest = tmp_path / "out.bin"
    _https_fetch("https://ok.test/x", dest, lambda done, total: beats.append((done, total)))
    assert dest.read_bytes() == b"zz"
    assert beats == [(2, None)]  # total unknown -> honest None, never guessed


# --------------------------------------------------------------------------- #
# _print_progress — throttled console output
# --------------------------------------------------------------------------- #


def test_print_progress_throttles_to_5pct_steps(capsys: pytest.CaptureFixture[str]) -> None:
    progress = _print_progress("model")
    progress(0, None)  # unknown total -> silent
    progress(50, 100)  # 50% -> prints
    progress(52, 100)  # 52% -> within 5% of last, suppressed
    progress(55, 100)  # 55% -> prints
    out = capsys.readouterr().out
    assert out.count("model:") == 2
    assert "50%" in out and "55%" in out and "52%" not in out


# --------------------------------------------------------------------------- #
# default_manifest_path / load_pinned_sha256_by_filename
# --------------------------------------------------------------------------- #


def test_default_manifest_path_points_at_packaging() -> None:
    path = default_manifest_path()
    assert path.name == "model-manifest.json"
    assert path.parent.name == "packaging"


def test_pinned_sha_missing_manifest_returns_empty(tmp_path: Path) -> None:
    # No pin file on disk -> empty map (download can complete but not verify).
    assert load_pinned_sha256_by_filename(tmp_path / "nope.json") == {}


# --------------------------------------------------------------------------- #
# keep_audio_directory — env resolution branches
# --------------------------------------------------------------------------- #


def test_keep_audio_dir_prefers_explicit_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OMNI_AUDIO_DIR", str(Path("D:/omni-audio")))
    assert keep_audio_directory() == Path("D:/omni-audio")


def test_keep_audio_dir_uses_localappdata(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OMNI_AUDIO_DIR", raising=False)
    monkeypatch.setenv("LOCALAPPDATA", str(Path("C:/Users/x/AppData/Local")))
    assert keep_audio_directory() == Path("C:/Users/x/AppData/Local") / "Omni" / "audio"


def test_keep_audio_dir_falls_back_to_home(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OMNI_AUDIO_DIR", raising=False)
    monkeypatch.delenv("LOCALAPPDATA", raising=False)
    assert keep_audio_directory() == Path.home() / ".local" / "share" / "Omni" / "audio"


# --------------------------------------------------------------------------- #
# KeepAudioRecorder — disabled short-circuit + fail-soft close
# --------------------------------------------------------------------------- #


def _frame(n: int = 32) -> Any:
    import numpy as np

    from engine.audio.audio_frame_types import AudioFrame, StreamLabel

    return AudioFrame(
        stream=StreamLabel.ME,
        samples=np.zeros(n, dtype=np.float32),
        t_start_monotonic=0.0,
    )


def test_write_frame_is_a_noop_once_disabled(tmp_path: Path) -> None:
    recorder = KeepAudioRecorder(tmp_path / "session")
    recorder._disabled = True  # simulate a prior write failure
    recorder.write_frame(_frame())
    # Disabled: no directory or file is ever created, no writer opened.
    assert not (tmp_path / "session").exists()
    assert recorder._writers == {}


def test_close_swallows_writer_errors_and_clears(tmp_path: Path) -> None:
    recorder = KeepAudioRecorder(tmp_path / "session")

    class _BoomWriter:
        def __init__(self) -> None:
            self.closed = False

        def close(self) -> None:
            self.closed = True
            raise OSError("disk gone")

    from engine.audio.audio_frame_types import StreamLabel

    boom = _BoomWriter()
    recorder._writers = {StreamLabel.ME: boom}  # type: ignore[dict-item]
    recorder.close()  # must NOT raise even though the writer errors
    assert boom.closed is True
    assert recorder._writers == {}  # cleared regardless of the failure


async def test_recorder_none_when_setting_read_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Fail closed on the retention DECISION: an unreadable setting => no keep.
    def _boom(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("db exploded")

    monkeypatch.setattr(keep_audio_recorder, "read_setting_bool", _boom)
    from engine.stt.keep_audio_recorder import create_keep_audio_recorder_if_enabled

    result = await create_keep_audio_recorder_if_enabled(None, "meeting-x")  # type: ignore[arg-type]
    assert result is None


# --------------------------------------------------------------------------- #
# CaptureModelLoader — fail-closed load paths
# --------------------------------------------------------------------------- #


def _vad_file(models_dir: Path) -> None:
    models_dir.mkdir(parents=True, exist_ok=True)
    (models_dir / SILERO_VAD_FILENAME).write_bytes(b"fake-onnx")


async def test_loader_fails_closed_when_vad_missing(tmp_path: Path) -> None:
    loader = CaptureModelLoader(models_dir=tmp_path / "empty")
    with pytest.raises(CaptureServiceError, match="VAD model missing"):
        await loader.ensure_loaded()
    assert loader.is_ready is False


async def test_loader_fails_closed_when_stt_deps_absent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from engine.stt import live_transcriber_factory

    _vad_file(tmp_path)
    monkeypatch.setattr(live_transcriber_factory, "stt_dependencies_available", lambda: False)
    loader = CaptureModelLoader(models_dir=tmp_path)
    with pytest.raises(CaptureServiceError, match="dependencies not installed"):
        await loader.ensure_loaded()
    assert loader.is_ready is False
    # The VAD factory WAS assigned before the transcriber step failed.
    assert loader.vad_factory is not None


async def test_loader_builds_parakeet_then_fails_closed_on_missing_checkpoint(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from engine.stt import live_transcriber_factory

    _vad_file(tmp_path)
    # Deps "present" so the loader constructs the real transcriber and calls
    # load() off-thread; the checkpoint is absent so load() fails closed.
    monkeypatch.setattr(live_transcriber_factory, "stt_dependencies_available", lambda: True)
    # Neutralise torch import inside load() should it get that far (it must not:
    # the file check precedes any import), but keep the env hermetic regardless.
    monkeypatch.setitem(sys.modules, "torch", types.ModuleType("torch"))
    loader = CaptureModelLoader(models_dir=tmp_path)
    with pytest.raises(FileNotFoundError, match="Parakeet model not found"):
        await loader.ensure_loaded()
    assert loader.is_ready is False
    assert loader.transcriber is not None  # constructed before the load failed


async def test_loader_ready_and_idempotent_with_injected_fakes(tmp_path: Path) -> None:
    class _FakeTranscriber:
        def __init__(self) -> None:
            self.load_calls = 0

        @property
        def is_loaded(self) -> bool:
            return self.load_calls > 0

        def load(self) -> None:
            self.load_calls += 1

    transcriber = _FakeTranscriber()
    loader = CaptureModelLoader(
        models_dir=tmp_path,
        transcriber=transcriber,  # type: ignore[arg-type]
        vad_factory=lambda: (lambda chunk: 0.0),
    )
    await loader.ensure_loaded()
    assert loader.is_ready is True
    assert transcriber.load_calls == 1
    await loader.ensure_loaded()  # already ready -> early return, no reload
    assert transcriber.load_calls == 1


async def test_loader_builds_openai_compatible_and_reports_cloud_status(
    tmp_path: Path,
) -> None:
    """Cloud STT must not fall through to Parakeet; status must report cloud."""
    from engine.stt.openai_compatible_stt import OpenAiCompatibleSttBackend
    from engine.stt.stt_runtime_status import get_stt_runtime_status, update_stt_runtime_status

    _vad_file(tmp_path)
    update_stt_runtime_status(engine="parakeet", model_id="", device="cpu")
    loader = CaptureModelLoader(models_dir=tmp_path, vad_factory=lambda: (lambda chunk: 0.0))
    loader.configure(
        "openai_compatible",
        "whisper-1",
        openai_base_url="https://api.openai.com/v1",
        openai_api_key="sk-test",
    )
    await loader.ensure_loaded()
    assert loader.is_ready is True
    assert isinstance(loader.transcriber, OpenAiCompatibleSttBackend)
    status = get_stt_runtime_status()
    assert status.engine == "openai_compatible"
    assert status.model_id == "whisper-1"
    assert status.device == "cloud"


async def test_loader_openai_compatible_fails_closed_without_key_or_url(
    tmp_path: Path,
) -> None:
    _vad_file(tmp_path)
    loader = CaptureModelLoader(models_dir=tmp_path, vad_factory=lambda: (lambda chunk: 0.0))
    loader.configure("openai_compatible", "whisper-1", openai_base_url="", openai_api_key=None)
    with pytest.raises(CaptureServiceError, match="openai_compatible"):
        await loader.ensure_loaded()
    assert loader.is_ready is False
