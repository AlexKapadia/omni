"""bge-small-en-v1.5 ONNX embedder (384-dim) for contextualized chunks.

Purpose: the dense side of the hybrid retriever — embeds contextualized
chunk text and queries with the SAME model (bge-small-en-v1.5, 33M params,
CPU-fast; kept for v1 per the M3 recommendation's evidence).
Pipeline position: called by the vault indexer (chunk embedding) and the
hybrid retriever (query embedding); output vectors land in
``engine.index.sqlite_vec_store``.

Local-only invariant: embedding is fully on-device (onnxruntime CPU/GPU);
chunk text never leaves the machine here.

Dependencies (LAZY, fail closed): ``onnxruntime`` is a runtime dep already;
the ``tokenizers`` package is pending (docs/progress/pending-deps.txt) and
is imported via ``importlib`` at first use — a clear
``IndexDependencyMissingError`` is raised when it (or the model files) are
absent, and unit tests mock at the ``EmbedderProtocol`` boundary. Model
files live under ``OMNI_MODELS_DIR/bge-small-en-v1.5/``
(model.onnx + tokenizer.json), fetched by the packaging model manifest.

Pooling: BGE models use the CLS token (first token of last_hidden_state),
then L2 normalisation — per the official BAAI/FlagEmbedding usage docs.
"""

import importlib
import os
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Protocol

import numpy as np

from engine.index.index_layer_errors import IndexDependencyMissingError

EMBEDDING_DIMENSIONS = 384
MODEL_SUBDIRECTORY = "bge-small-en-v1.5"
_MAX_MODEL_TOKENS = 512  # bge-small's context window; tokenizer truncates to it


class EmbedderProtocol(Protocol):
    """Mockable embedding boundary: texts in, 384-dim unit vectors out."""

    def embed_batch(self, texts: Sequence[str]) -> list[list[float]]:
        """Embed a batch; returns one EMBEDDING_DIMENSIONS vector per text."""
        ...


def _default_model_dir() -> Path:
    """OMNI_MODELS_DIR (or %LOCALAPPDATA%/Omni/models) / bge-small-en-v1.5."""
    override = os.environ.get("OMNI_MODELS_DIR")
    if override:
        return Path(override) / MODEL_SUBDIRECTORY
    local_app_data = os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local"))
    return Path(local_app_data) / "Omni" / "models" / MODEL_SUBDIRECTORY


class BgeSmallOnnxEmbedder:
    """Batch embedder over the local bge-small-en-v1.5 ONNX export.

    Loading is deferred to first use so importing this module (and running
    the engine without the dense path) costs nothing and cannot fail.
    """

    def __init__(self, model_dir: Path | None = None) -> None:
        self._model_dir = model_dir if model_dir is not None else _default_model_dir()
        self._session: Any | None = None
        self._tokenizer: Any | None = None

    def _ensure_loaded(self) -> tuple[Any, Any]:
        """Lazy-load onnxruntime + tokenizer + model files; fail closed.

        Returns ``(tokenizer, session)`` so callers get non-None handles
        without runtime asserts.
        """
        if self._session is not None:
            return self._tokenizer, self._session
        try:
            onnxruntime = importlib.import_module("onnxruntime")
        except ImportError as exc:  # fail closed with an actionable message
            raise IndexDependencyMissingError(
                "onnxruntime is required for dense embedding but is not "
                "installed (runtime dependency of the engine)."
            ) from exc
        try:
            # importlib (not a static import): 'tokenizers' is a PENDING dep —
            # see docs/progress/pending-deps.txt — so a static import would
            # trip strict mypy before the orchestrator lands it.
            tokenizers_module = importlib.import_module("tokenizers")
        except ImportError as exc:
            raise IndexDependencyMissingError(
                "the 'tokenizers' package is required for dense embedding but "
                "is not installed — tracked in docs/progress/pending-deps.txt."
            ) from exc
        model_path = self._model_dir / "model.onnx"
        tokenizer_path = self._model_dir / "tokenizer.json"
        if not model_path.is_file() or not tokenizer_path.is_file():
            raise IndexDependencyMissingError(
                f"bge-small-en-v1.5 model files missing under {self._model_dir} "
                "(expected model.onnx + tokenizer.json; fetched by the "
                "packaging model manifest)."
            )
        tokenizer = tokenizers_module.Tokenizer.from_file(str(tokenizer_path))
        tokenizer.enable_truncation(max_length=_MAX_MODEL_TOKENS)
        tokenizer.enable_padding()
        self._tokenizer = tokenizer
        self._session = onnxruntime.InferenceSession(
            str(model_path), providers=["CPUExecutionProvider"]
        )
        return self._tokenizer, self._session

    def embed_batch(self, texts: Sequence[str]) -> list[list[float]]:
        """Embed texts → L2-normalised 384-dim vectors (CLS pooling).

        Deterministic for identical inputs (same model, same tokenizer,
        CPU provider). Raises ``IndexDependencyMissingError`` when the
        dependency or model files are absent (fail closed, never guess).
        """
        if not texts:
            return []
        tokenizer, session = self._ensure_loaded()
        encodings = tokenizer.encode_batch(list(texts))
        input_ids = np.array([e.ids for e in encodings], dtype=np.int64)
        attention_mask = np.array([e.attention_mask for e in encodings], dtype=np.int64)
        feeds: dict[str, Any] = {
            "input_ids": input_ids,
            "attention_mask": attention_mask,
        }
        # Some BERT-family exports also require token_type_ids; feed zeros.
        session_inputs = {i.name for i in session.get_inputs()}
        if "token_type_ids" in session_inputs:
            feeds["token_type_ids"] = np.zeros_like(input_ids)
        last_hidden_state = session.run(None, feeds)[0]
        cls_vectors = np.asarray(last_hidden_state)[:, 0, :]  # CLS pooling (BGE docs)
        norms = np.linalg.norm(cls_vectors, axis=1, keepdims=True)
        norms[norms == 0.0] = 1.0  # degenerate all-zero row: leave unnormalised
        normalised = cls_vectors / norms
        if normalised.shape[1] != EMBEDDING_DIMENSIONS:
            raise IndexDependencyMissingError(  # wrong model file: fail closed
                f"embedding model produced {normalised.shape[1]}-dim vectors; "
                f"expected {EMBEDDING_DIMENSIONS} (is the ONNX export bge-small-en-v1.5?)"
            )
        return [[float(x) for x in row] for row in normalised]
