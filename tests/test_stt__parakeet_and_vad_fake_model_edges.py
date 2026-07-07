"""Fake-model edges for the two STT model wrappers + the word-token contract.

The heavy libraries (torch / NeMo for Parakeet, onnxruntime for Silero) are
lazy-imported inside these modules, so we inject FAKES via ``sys.modules`` and
assert the wiring/parse/fail-closed logic AROUND the un-fakeable model call —
never real inference. Every test asserts an exact behaviour that would break
if the code were wrong (device/dtype selection, OOM fallback, verbatim word
assembly, the v5 64-sample context-carry contract, threshold-shaped output).
"""

import sys
import types
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from engine.stt.parakeet_nemo_transcriber import (
    ParakeetNemoTranscriber,
    _words_from_hypotheses,
    stt_dependencies_available,
)
from engine.stt.silero_onnx_voice_activity_detector import (
    VAD_CHUNK_SAMPLES,
    SileroOnnxVoiceActivityDetector,
)
from engine.stt.word_token_types import TranscribedWindow, WordToken

# --------------------------------------------------------------------------- #
# Fake torch / NeMo scaffolding for ParakeetNemoTranscriber
# --------------------------------------------------------------------------- #


class _FakeOutOfMemoryError(Exception):
    """Stand-in for ``torch.cuda.OutOfMemoryError`` (caught by name in load())."""


class _FakeCuda:
    def __init__(self, available: bool, capability: tuple[int, int]) -> None:
        self._available = available
        self._capability = capability
        self.empty_cache_calls = 0
        self.OutOfMemoryError = _FakeOutOfMemoryError

    def is_available(self) -> bool:
        return self._available

    def get_device_capability(self, index: int) -> tuple[int, int]:
        assert index == 0  # the module always probes device 0
        return self._capability

    def empty_cache(self) -> None:
        self.empty_cache_calls += 1


def _make_fake_torch(*, cuda_available: bool, capability: tuple[int, int]) -> Any:
    torch = types.ModuleType("torch")
    torch.cuda = _FakeCuda(cuda_available, capability)  # type: ignore[attr-defined]
    torch.bfloat16 = "BF16"  # type: ignore[attr-defined]
    torch.float16 = "FP16"  # type: ignore[attr-defined]

    @contextmanager
    def inference_mode() -> Iterator[None]:
        yield

    @contextmanager
    def autocast(device_type: str, dtype: Any) -> Iterator[None]:
        # Record that the autocast branch was taken with the loaded dtype.
        torch.autocast_calls.append((device_type, dtype))
        yield

    torch.autocast_calls = []  # type: ignore[attr-defined]
    torch.inference_mode = inference_mode  # type: ignore[attr-defined]
    torch.autocast = autocast  # type: ignore[attr-defined]
    return torch


class _FakeModel:
    def __init__(self, hypotheses: Any) -> None:
        self._hypotheses = hypotheses
        self.eval_called = False
        self.to_device: str | None = None
        self.transcribe_batch_sizes: list[int] = []

    def eval(self) -> None:
        self.eval_called = True

    def to(self, device: str) -> "_FakeModel":
        self.to_device = device
        return self

    def transcribe(self, audio: Any, batch_size: int, timestamps: bool, verbose: bool) -> Any:
        # The contract the transcriber MUST honour: word timestamps on, quiet.
        assert timestamps is True
        assert verbose is False
        self.transcribe_batch_sizes.append(batch_size)
        return self._hypotheses


class _Hypothesis:
    def __init__(self, words: list[dict[str, Any]]) -> None:
        self.timestamp = {"word": words}


def _install_fakes(
    monkeypatch: pytest.MonkeyPatch,
    *,
    torch: Any,
    restore_from: Any,
) -> None:
    monkeypatch.setitem(sys.modules, "torch", torch)
    nemo = types.ModuleType("nemo")
    collections = types.ModuleType("nemo.collections")
    asr = types.ModuleType("nemo.collections.asr")
    asr.models = types.SimpleNamespace(  # type: ignore[attr-defined]
        ASRModel=types.SimpleNamespace(restore_from=restore_from)
    )
    collections.asr = asr  # type: ignore[attr-defined]
    nemo.collections = collections  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "nemo", nemo)
    monkeypatch.setitem(sys.modules, "nemo.collections", collections)
    monkeypatch.setitem(sys.modules, "nemo.collections.asr", asr)


def _model_file(tmp_path: Path) -> Path:
    path = tmp_path / "parakeet.nemo"
    path.write_bytes(b"fake-checkpoint")  # is_file() gate only; never parsed
    return path


# --------------------------------------------------------------------------- #
# stt_dependencies_available
# --------------------------------------------------------------------------- #


def test_deps_available_true_when_both_importable(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_fakes(
        monkeypatch,
        torch=_make_fake_torch(cuda_available=False, capability=(0, 0)),
        restore_from=lambda *a, **k: _FakeModel([]),
    )
    assert stt_dependencies_available() is True


def test_deps_available_false_when_torch_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    # nemo present but torch absent -> ImportError -> honest False.
    _install_fakes(
        monkeypatch,
        torch=_make_fake_torch(cuda_available=False, capability=(0, 0)),
        restore_from=lambda *a, **k: _FakeModel([]),
    )
    monkeypatch.setitem(sys.modules, "torch", None)
    assert stt_dependencies_available() is False


# --------------------------------------------------------------------------- #
# load() — fail-closed, device/dtype selection, idempotence, OOM fallback
# --------------------------------------------------------------------------- #


def test_load_fails_closed_on_missing_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _install_fakes(
        monkeypatch,
        torch=_make_fake_torch(cuda_available=False, capability=(0, 0)),
        restore_from=lambda *a, **k: _FakeModel([]),
    )
    transcriber = ParakeetNemoTranscriber(tmp_path / "does-not-exist.nemo")
    assert transcriber.is_loaded is False
    with pytest.raises(FileNotFoundError, match="Parakeet model not found"):
        transcriber.load()
    assert transcriber.is_loaded is False  # still honest after failure


def test_load_cpu_when_no_cuda(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    model = _FakeModel([])
    captured: dict[str, Any] = {}

    def restore_from(path: str, map_location: str) -> _FakeModel:
        captured["map_location"] = map_location
        return model

    _install_fakes(
        monkeypatch,
        torch=_make_fake_torch(cuda_available=False, capability=(0, 0)),
        restore_from=restore_from,
    )
    transcriber = ParakeetNemoTranscriber(_model_file(tmp_path))
    transcriber.load()
    assert transcriber.is_loaded is True
    assert transcriber._device == "cpu"
    assert transcriber._autocast_dtype is None  # no autocast on CPU
    assert captured["map_location"] == "cpu"
    assert model.eval_called is True and model.to_device == "cpu"


def test_load_cuda_ampere_selects_bfloat16(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    torch = _make_fake_torch(cuda_available=True, capability=(8, 6))  # RTX 4070-class
    _install_fakes(monkeypatch, torch=torch, restore_from=lambda *a, **k: _FakeModel([]))
    transcriber = ParakeetNemoTranscriber(_model_file(tmp_path))
    transcriber.load()
    assert transcriber._device == "cuda"
    assert transcriber._autocast_dtype == "BF16"  # >= 8.x -> bfloat16, exact


def test_load_cuda_pre_ampere_selects_float16(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    torch = _make_fake_torch(cuda_available=True, capability=(7, 5))  # Turing-class
    _install_fakes(monkeypatch, torch=torch, restore_from=lambda *a, **k: _FakeModel([]))
    transcriber = ParakeetNemoTranscriber(_model_file(tmp_path))
    transcriber.load()
    assert transcriber._autocast_dtype == "FP16"  # < 8.x -> float16, exact


def test_load_is_idempotent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls = {"n": 0}

    def restore_from(path: str, map_location: str) -> _FakeModel:
        calls["n"] += 1
        return _FakeModel([])

    _install_fakes(
        monkeypatch,
        torch=_make_fake_torch(cuda_available=False, capability=(0, 0)),
        restore_from=restore_from,
    )
    transcriber = ParakeetNemoTranscriber(_model_file(tmp_path))
    transcriber.load()
    transcriber.load()  # second call must early-return, never reload
    assert calls["n"] == 1


def test_load_falls_back_to_cpu_on_cuda_oom(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    torch = _make_fake_torch(cuda_available=True, capability=(8, 9))
    seen_locations: list[str] = []

    def restore_from(path: str, map_location: str) -> _FakeModel:
        seen_locations.append(map_location)
        if map_location == "cuda":
            raise _FakeOutOfMemoryError("simulated OOM at load")
        return _FakeModel([])

    _install_fakes(monkeypatch, torch=torch, restore_from=restore_from)
    transcriber = ParakeetNemoTranscriber(_model_file(tmp_path))
    transcriber.load()
    # It tried CUDA, OOM'd, cleared the cache, then loaded on CPU (honest fallback).
    assert seen_locations == ["cuda", "cpu"]
    assert transcriber._device == "cpu"
    assert transcriber._autocast_dtype is None
    assert torch.cuda.empty_cache_calls == 1


# --------------------------------------------------------------------------- #
# transcribe_window — fail-closed, empty short-circuit, autocast vs plain
# --------------------------------------------------------------------------- #


def test_transcribe_before_load_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_fakes(
        monkeypatch,
        torch=_make_fake_torch(cuda_available=False, capability=(0, 0)),
        restore_from=lambda *a, **k: _FakeModel([]),
    )
    transcriber = ParakeetNemoTranscriber(_model_file(tmp_path))
    with pytest.raises(RuntimeError, match="used before load"):
        transcriber.transcribe_window(np.zeros(16_000, dtype=np.float32))


def test_transcribe_empty_returns_no_words(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    nonempty = _Hypothesis([{"word": "x", "start": 0, "end": 1}])
    _install_fakes(
        monkeypatch,
        torch=_make_fake_torch(cuda_available=False, capability=(0, 0)),
        restore_from=lambda *a, **k: _FakeModel([nonempty]),
    )
    transcriber = ParakeetNemoTranscriber(_model_file(tmp_path))
    transcriber.load()
    # Zero-length window must short-circuit to [] WITHOUT invoking the model.
    assert transcriber.transcribe_window(np.zeros(0, dtype=np.float32)) == []


def test_transcribe_cpu_returns_verbatim_words(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    hyp = _Hypothesis(
        [
            {"word": "Héllo", "start": 0.10, "end": 0.40},
            {"word": "wörld", "start": 0.41, "end": 0.90},
        ]
    )
    torch = _make_fake_torch(cuda_available=False, capability=(0, 0))
    _install_fakes(monkeypatch, torch=torch, restore_from=lambda *a, **k: _FakeModel([hyp]))
    transcriber = ParakeetNemoTranscriber(_model_file(tmp_path))
    transcriber.load()
    words = transcriber.transcribe_window(np.ones(8_000, dtype=np.float32))
    assert [w.text for w in words] == ["Héllo", "wörld"]  # verbatim, casing kept
    assert words[0].t_start == 0.10 and words[0].t_end == 0.40
    assert torch.autocast_calls == []  # CPU path never enters autocast


def test_transcribe_cuda_uses_autocast_with_loaded_dtype(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    hyp = _Hypothesis([{"word": "ok", "start": 0.0, "end": 0.2}])
    torch = _make_fake_torch(cuda_available=True, capability=(8, 6))
    _install_fakes(monkeypatch, torch=torch, restore_from=lambda *a, **k: _FakeModel([hyp]))
    transcriber = ParakeetNemoTranscriber(_model_file(tmp_path))
    transcriber.load()
    torch.autocast_calls.clear()  # ignore warm-up's autocast entry
    words = transcriber.transcribe_window(np.ones(4_000, dtype=np.float32))
    assert [w.text for w in words] == ["ok"]
    # The CUDA branch MUST run under autocast with the exact loaded dtype.
    assert torch.autocast_calls == [("cuda", "BF16")]


# --------------------------------------------------------------------------- #
# _words_from_hypotheses — pure parse edges
# --------------------------------------------------------------------------- #


def test_words_from_empty_hypotheses_is_empty() -> None:
    assert _words_from_hypotheses([]) == []
    assert _words_from_hypotheses(None) == []


def test_words_from_hypothesis_without_timestamp_is_empty() -> None:
    class _NoTs:
        timestamp = None

    assert _words_from_hypotheses([_NoTs()]) == []


def test_words_from_hypothesis_coerces_types_verbatim() -> None:
    hyp = _Hypothesis([{"word": 123, "start": "0.5", "end": 1}])  # odd types on purpose
    words = _words_from_hypotheses([hyp])
    assert len(words) == 1
    assert words[0].text == "123"  # str() coercion, still verbatim content
    assert words[0].t_start == 0.5 and words[0].t_end == 1.0


# --------------------------------------------------------------------------- #
# SileroOnnxVoiceActivityDetector — fake onnxruntime session
# --------------------------------------------------------------------------- #


class _FakeSession:
    def __init__(self, path: str, providers: list[str]) -> None:
        self.path = path
        self.providers = providers
        self.feeds: list[dict[str, Any]] = []
        # Default output: probability + a mutated recurrent state.
        self._prob = np.array([[0.5]], dtype=np.float32)
        self._next_state = np.ones((2, 1, 128), dtype=np.float32)

    def set_probability(self, value: float) -> None:
        self._prob = np.array([[value]], dtype=np.float32)

    def run(self, output_names: Any, feed: dict[str, Any]) -> list[Any]:
        self.feeds.append({k: np.array(v, copy=True) for k, v in feed.items()})
        return [self._prob, self._next_state]


def _install_fake_onnx(monkeypatch: pytest.MonkeyPatch) -> None:
    ort = types.ModuleType("onnxruntime")
    ort.InferenceSession = _FakeSession  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "onnxruntime", ort)


def _vad_model_file(tmp_path: Path) -> Path:
    path = tmp_path / "silero_vad.onnx"
    path.write_bytes(b"fake-onnx")  # is_file() gate only
    return path


def test_vad_fails_closed_on_missing_model(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_fake_onnx(monkeypatch)
    with pytest.raises(FileNotFoundError, match="Silero VAD model not found"):
        SileroOnnxVoiceActivityDetector(tmp_path / "absent.onnx")


def test_vad_rejects_wrong_sized_chunk(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _install_fake_onnx(monkeypatch)
    vad = SileroOnnxVoiceActivityDetector(_vad_model_file(tmp_path))
    with pytest.raises(ValueError, match=f"exactly {VAD_CHUNK_SAMPLES} samples"):
        vad(np.zeros(VAD_CHUNK_SAMPLES - 1, dtype=np.float32))
    with pytest.raises(ValueError, match="exactly"):
        vad(np.zeros(VAD_CHUNK_SAMPLES + 1, dtype=np.float32))


@pytest.mark.parametrize("prob", [0.0, 0.4999, 0.5, 0.5001, 1.0])
def test_vad_returns_probability_verbatim(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, prob: float
) -> None:
    _install_fake_onnx(monkeypatch)
    vad = SileroOnnxVoiceActivityDetector(_vad_model_file(tmp_path))
    session: _FakeSession = vad._session
    session.set_probability(prob)
    out = vad(np.zeros(VAD_CHUNK_SAMPLES, dtype=np.float32))
    # The wrapper must pass the model's probability through byte-exactly.
    assert out == pytest.approx(prob, abs=1e-7)
    assert isinstance(out, float)


def test_vad_carries_64_sample_context_across_calls(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_fake_onnx(monkeypatch)
    vad = SileroOnnxVoiceActivityDetector(_vad_model_file(tmp_path))
    session: _FakeSession = vad._session

    chunk1 = np.arange(VAD_CHUNK_SAMPLES, dtype=np.float32) + 1.0  # distinctive, non-zero
    vad(chunk1)
    first_input = session.feeds[0]["input"].reshape(-1)
    assert first_input.shape == (VAD_CHUNK_SAMPLES + 64,)  # context + chunk
    # First call: context is zeros (no prior chunk yet).
    assert np.all(first_input[:64] == 0.0)
    assert np.array_equal(first_input[64:], chunk1)

    chunk2 = np.full(VAD_CHUNK_SAMPLES, 7.0, dtype=np.float32)
    vad(chunk2)
    second_input = session.feeds[1]["input"].reshape(-1)
    # v5 contract: the prepended context is the LAST 64 samples of chunk1.
    assert np.array_equal(second_input[:64], chunk1[-64:])
    assert np.array_equal(second_input[64:], chunk2)


def test_vad_reset_zeros_state_and_context(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_fake_onnx(monkeypatch)
    vad = SileroOnnxVoiceActivityDetector(_vad_model_file(tmp_path))
    vad(np.full(VAD_CHUNK_SAMPLES, 3.0, dtype=np.float32))
    # After a call, state was replaced by the model's output and context is non-zero.
    assert np.any(vad._state != 0.0)
    assert np.any(vad._context != 0.0)
    vad.reset()
    assert np.all(vad._state == 0.0)
    assert np.all(vad._context == 0.0)
    # After reset the next call's context is zeros again (clean stream boundary).
    vad(np.full(VAD_CHUNK_SAMPLES, 9.0, dtype=np.float32))
    session: _FakeSession = vad._session
    assert np.all(session.feeds[-1]["input"].reshape(-1)[:64] == 0.0)


# --------------------------------------------------------------------------- #
# word_token_types — TranscribedWindow validation edges
# --------------------------------------------------------------------------- #


def test_transcribed_window_rejects_inverted_bounds() -> None:
    with pytest.raises(ValueError, match="t_end < t_start"):
        TranscribedWindow(index=0, t_start=1.0, t_end=0.5, words=())


def test_transcribed_window_rejects_negative_index() -> None:
    with pytest.raises(ValueError, match="index must be >= 0"):
        TranscribedWindow(index=-1, t_start=0.0, t_end=1.0, words=())


def test_transcribed_window_accepts_zero_length_and_zero_index() -> None:
    # Boundary just-inside: index 0 and t_end == t_start are both legal.
    window = TranscribedWindow(
        index=0, t_start=2.0, t_end=2.0, words=(WordToken("a", 2.0, 2.0),)
    )
    assert window.index == 0 and window.t_end == window.t_start
