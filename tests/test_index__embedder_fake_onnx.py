"""BgeSmallOnnxEmbedder exercised end-to-end with FAKE onnxruntime/tokenizer.

We never load a real model (no GPU, no network, no model math). Instead we
inject fake ``onnxruntime`` + ``tokenizers`` modules and a controlled
``last_hidden_state`` so we can assert the module's OWN logic exactly:
CLS pooling (token 0, not mean), L2 normalisation to unit length, the
degenerate all-zero row staying zero (never NaN), token_type_ids feeding,
lazy-load caching, truncation config, and fail-closed on a wrong output dim.
"""

import importlib
import math
import types
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from engine.index.bge_small_onnx_embedder import (
    EMBEDDING_DIMENSIONS,
    BgeSmallOnnxEmbedder,
    _default_model_dir,
)
from engine.index.index_layer_errors import IndexDependencyMissingError


class _FakeEncoding:
    def __init__(self, ids: list[int]) -> None:
        self.ids = ids
        self.attention_mask = [1] * len(ids)


class _FakeTokenizer:
    """Records truncation/padding config; two-token encodings per text."""

    def __init__(self) -> None:
        self.truncation_max_length: int | None = None
        self.padding_enabled = False

    def enable_truncation(self, max_length: int) -> None:
        self.truncation_max_length = max_length

    def enable_padding(self) -> None:
        self.padding_enabled = True

    def encode_batch(self, texts: list[str]) -> list[_FakeEncoding]:
        return [_FakeEncoding([101, 102]) for _ in texts]


class _FakeSessionInput:
    def __init__(self, name: str) -> None:
        self.name = name


class _FakeSession:
    """Returns a fixed hidden state; records the feeds it was given."""

    def __init__(self, hidden_state: np.ndarray, input_names: tuple[str, ...]) -> None:
        self._hidden_state = hidden_state
        self._input_names = input_names
        self.last_feeds: dict[str, Any] | None = None

    def get_inputs(self) -> list[_FakeSessionInput]:
        return [_FakeSessionInput(name) for name in self._input_names]

    def run(self, _outputs: Any, feeds: dict[str, Any]) -> list[np.ndarray]:
        self.last_feeds = feeds
        return [self._hidden_state]


def _install_fake_deps(
    monkeypatch: pytest.MonkeyPatch,
    model_dir: Path,
    tokenizer: _FakeTokenizer,
    session: _FakeSession,
) -> dict[str, int]:
    """Create model files + patch importlib; return load-call counters."""
    model_dir.mkdir(parents=True, exist_ok=True)
    (model_dir / "model.onnx").write_bytes(b"")
    (model_dir / "tokenizer.json").write_text("{}", encoding="utf-8")
    counters = {"from_file": 0, "session": 0}
    real_import = importlib.import_module

    def from_file(_path: str) -> _FakeTokenizer:
        counters["from_file"] += 1
        return tokenizer

    def inference_session(_path: str, providers: list[str]) -> _FakeSession:
        counters["session"] += 1
        assert providers == ["CPUExecutionProvider"]  # least-privilege: CPU only
        return session

    tokenizers_mod = types.SimpleNamespace(
        Tokenizer=types.SimpleNamespace(from_file=from_file)
    )
    onnxruntime_mod = types.SimpleNamespace(InferenceSession=inference_session)

    def fake_import(name: str, package: str | None = None) -> types.ModuleType:
        if name == "tokenizers":
            return tokenizers_mod  # type: ignore[return-value]
        if name == "onnxruntime":
            return onnxruntime_mod  # type: ignore[return-value]
        return real_import(name, package)

    monkeypatch.setattr(importlib, "import_module", fake_import)
    return counters


def test_cls_pooling_and_l2_normalisation_are_exact(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # token 0 (CLS) differs from token 1; if the code averaged or picked the
    # wrong token the axis-0-unit result would NOT appear.
    hidden = np.zeros((2, 2, EMBEDDING_DIMENSIONS), dtype=np.float32)
    hidden[0, 0, 0] = 2.0  # row 0 CLS -> unit axis 0 after normalisation
    hidden[0, 1, :] = 5.0  # row 0 token 1 -> must be ignored (not CLS)
    hidden[1, 0, 1] = 3.0  # row 1 CLS -> unit axis 1
    tokenizer, session = _FakeTokenizer(), _FakeSession(hidden, ("input_ids", "attention_mask"))
    _install_fake_deps(monkeypatch, tmp_path, tokenizer, session)

    vectors = BgeSmallOnnxEmbedder(model_dir=tmp_path).embed_batch(["a", "b"])

    assert len(vectors) == 2 and all(len(v) == EMBEDDING_DIMENSIONS for v in vectors)
    assert vectors[0][0] == 1.0 and vectors[0][1] == 0.0  # CLS token, unit length
    assert all(x == 0.0 for x in vectors[0][1:])
    assert vectors[1][1] == 1.0 and vectors[1][0] == 0.0
    for vector in vectors:
        assert math.isclose(sum(x * x for x in vector), 1.0, abs_tol=1e-6)
    # truncation/padding configured to bge-small's window.
    assert tokenizer.truncation_max_length == 512
    assert tokenizer.padding_enabled is True


def test_non_axis_aligned_row_normalises_to_unit_length(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    hidden = np.zeros((1, 1, EMBEDDING_DIMENSIONS), dtype=np.float32)
    hidden[0, 0, 0] = 3.0
    hidden[0, 0, 1] = 4.0  # CLS magnitude 5 -> normalises to 0.6, 0.8
    session = _FakeSession(hidden, ("input_ids", "attention_mask"))
    _install_fake_deps(monkeypatch, tmp_path, _FakeTokenizer(), session)

    vector = BgeSmallOnnxEmbedder(model_dir=tmp_path).embed_batch(["x"])[0]

    assert math.isclose(vector[0], 0.6, abs_tol=1e-6)
    assert math.isclose(vector[1], 0.8, abs_tol=1e-6)


def test_degenerate_all_zero_row_stays_zero_never_nan(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    hidden = np.zeros((1, 2, EMBEDDING_DIMENSIONS), dtype=np.float32)  # CLS all zero
    session = _FakeSession(hidden, ("input_ids", "attention_mask"))
    _install_fake_deps(monkeypatch, tmp_path, _FakeTokenizer(), session)

    vector = BgeSmallOnnxEmbedder(model_dir=tmp_path).embed_batch(["zero"])[0]

    assert all(x == 0.0 for x in vector)  # divide-by-zero guarded (norm set to 1.0)
    assert not any(math.isnan(x) for x in vector)


def test_token_type_ids_fed_only_when_the_model_declares_them(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    hidden = np.zeros((1, 2, EMBEDDING_DIMENSIONS), dtype=np.float32)
    hidden[0, 0, 0] = 1.0
    with_tti = _FakeSession(hidden, ("input_ids", "attention_mask", "token_type_ids"))
    _install_fake_deps(monkeypatch, tmp_path, _FakeTokenizer(), with_tti)
    BgeSmallOnnxEmbedder(model_dir=tmp_path).embed_batch(["a"])
    assert with_tti.last_feeds is not None
    assert "token_type_ids" in with_tti.last_feeds
    assert np.array_equal(
        with_tti.last_feeds["token_type_ids"], np.zeros_like(with_tti.last_feeds["input_ids"])
    )


def test_token_type_ids_omitted_when_model_does_not_declare_them(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    hidden = np.zeros((1, 2, EMBEDDING_DIMENSIONS), dtype=np.float32)
    hidden[0, 0, 0] = 1.0
    without_tti = _FakeSession(hidden, ("input_ids", "attention_mask"))
    _install_fake_deps(monkeypatch, tmp_path, _FakeTokenizer(), without_tti)
    BgeSmallOnnxEmbedder(model_dir=tmp_path).embed_batch(["a"])
    assert without_tti.last_feeds is not None
    assert "token_type_ids" not in without_tti.last_feeds


def test_wrong_output_dimension_fails_closed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    hidden = np.ones((1, 2, 100), dtype=np.float32)  # not 384 -> wrong model export
    session = _FakeSession(hidden, ("input_ids", "attention_mask"))
    _install_fake_deps(monkeypatch, tmp_path, _FakeTokenizer(), session)
    with pytest.raises(IndexDependencyMissingError, match="expected 384"):
        BgeSmallOnnxEmbedder(model_dir=tmp_path).embed_batch(["x"])


def test_model_is_loaded_once_and_reused_across_calls(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    hidden = np.zeros((1, 2, EMBEDDING_DIMENSIONS), dtype=np.float32)
    hidden[0, 0, 0] = 1.0
    session = _FakeSession(hidden, ("input_ids", "attention_mask"))
    counters = _install_fake_deps(monkeypatch, tmp_path, _FakeTokenizer(), session)
    embedder = BgeSmallOnnxEmbedder(model_dir=tmp_path)
    embedder.embed_batch(["a"])
    embedder.embed_batch(["b"])
    assert counters == {"from_file": 1, "session": 1}  # cached, not reloaded


def test_onnxruntime_absence_fails_closed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    (tmp_path / "model.onnx").write_bytes(b"")
    (tmp_path / "tokenizer.json").write_text("{}", encoding="utf-8")
    real_import = importlib.import_module

    def fake_import(name: str, package: str | None = None) -> types.ModuleType:
        if name == "onnxruntime":
            raise ImportError("simulated absence")
        return real_import(name, package)

    monkeypatch.setattr(importlib, "import_module", fake_import)
    with pytest.raises(IndexDependencyMissingError, match="onnxruntime"):
        BgeSmallOnnxEmbedder(model_dir=tmp_path).embed_batch(["x"])


def test_default_model_dir_uses_localappdata_then_home_fallback(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("OMNI_MODELS_DIR", raising=False)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "lad"))
    assert _default_model_dir() == tmp_path / "lad" / "Omni" / "models" / "bge-small-en-v1.5"
    monkeypatch.delenv("LOCALAPPDATA", raising=False)
    expected = Path.home() / "AppData" / "Local" / "Omni" / "models" / "bge-small-en-v1.5"
    assert _default_model_dir() == expected
