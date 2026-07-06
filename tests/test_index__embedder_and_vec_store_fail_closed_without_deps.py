"""Fail-closed behaviour at every lazy heavy-dependency boundary.

The pending deps (tokenizers, sqlite-vec, watchdog — see
docs/progress/pending-deps.txt) are simulated as ABSENT regardless of the
machine's state by intercepting ``importlib.import_module``: each boundary
must raise ``IndexDependencyMissingError`` with an actionable message —
never a bare ImportError, never a silent no-op pretending the dense path ran.
"""

import importlib
import struct
import types
from collections.abc import Callable
from pathlib import Path

import pytest

from engine.index.bge_small_onnx_embedder import (
    EMBEDDING_DIMENSIONS,
    BgeSmallOnnxEmbedder,
    _default_model_dir,
)
from engine.index.index_layer_errors import IndexDependencyMissingError, IndexLayerError
from engine.index.sqlite_vec_store import SqliteVecStore, serialize_float32_vector
from engine.index.vault_watchdog_file_watcher import start_vault_file_watcher
from engine.storage import apply_migrations, open_sqlite_connection


def _blocking_import(
    blocked_prefixes: tuple[str, ...],
) -> Callable[..., types.ModuleType]:
    real_import = importlib.import_module

    def fake_import(name: str, package: str | None = None) -> types.ModuleType:
        if name.startswith(blocked_prefixes):
            raise ImportError(f"simulated absence of {name!r}")
        return real_import(name, package)

    return fake_import


def test_embedder_fails_closed_when_tokenizers_is_absent(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(importlib, "import_module", _blocking_import(("tokenizers",)))
    embedder = BgeSmallOnnxEmbedder(model_dir=tmp_path)
    with pytest.raises(IndexDependencyMissingError, match="tokenizers"):
        embedder.embed_batch(["text"])


def test_embedder_fails_closed_when_model_files_are_missing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # tokenizers "importable" (dummy module), but the model dir is empty:
    # the file check must fail closed BEFORE anything touches the dummy.
    real_import = importlib.import_module

    def fake_import(name: str, package: str | None = None) -> types.ModuleType:
        if name == "tokenizers":
            return types.SimpleNamespace(Tokenizer=None)  # type: ignore[return-value]
        return real_import(name, package)

    monkeypatch.setattr(importlib, "import_module", fake_import)
    embedder = BgeSmallOnnxEmbedder(model_dir=tmp_path / "no-model-here")
    with pytest.raises(IndexDependencyMissingError, match="model files missing"):
        embedder.embed_batch(["text"])


def test_embedder_empty_batch_never_touches_dependencies(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def exploding_import(name: str, package: str | None = None) -> types.ModuleType:
        raise AssertionError("no import may happen for an empty batch")

    monkeypatch.setattr(importlib, "import_module", exploding_import)
    assert BgeSmallOnnxEmbedder(model_dir=tmp_path).embed_batch([]) == []


def test_default_model_dir_respects_omni_models_dir_env(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("OMNI_MODELS_DIR", str(tmp_path / "models"))
    assert _default_model_dir() == tmp_path / "models" / "bge-small-en-v1.5"


async def test_vec_store_fails_closed_when_sqlite_vec_is_absent(
    monkeypatch: pytest.MonkeyPatch, tmp_db_path: Path, real_migrations_dir: Path
) -> None:
    await apply_migrations(tmp_db_path, real_migrations_dir)
    connection = await open_sqlite_connection(tmp_db_path)
    try:
        monkeypatch.setattr(importlib, "import_module", _blocking_import(("sqlite_vec",)))
        store = SqliteVecStore(connection)
        with pytest.raises(IndexDependencyMissingError, match="sqlite-vec"):
            await store.knn_chunk_ids([0.0] * EMBEDDING_DIMENSIONS, 10)
        with pytest.raises(IndexDependencyMissingError, match="sqlite-vec"):
            await store.upsert_chunk_embeddings([(1, [0.0] * EMBEDDING_DIMENSIONS)])
        with pytest.raises(IndexDependencyMissingError, match="sqlite-vec"):
            await store.delete_chunk_embeddings([1])
    finally:
        await connection.close()


def test_watcher_fails_closed_when_watchdog_is_absent(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(importlib, "import_module", _blocking_import(("watchdog",)))
    with pytest.raises(IndexDependencyMissingError, match="watchdog"):
        start_vault_file_watcher(tmp_path, lambda paths: None)


def test_vector_serialisation_is_exact_little_endian_float32() -> None:
    vector = [0.0] * EMBEDDING_DIMENSIONS
    vector[0], vector[383] = 1.5, -2.25  # exactly representable in float32
    blob = serialize_float32_vector(vector)
    assert len(blob) == EMBEDDING_DIMENSIONS * 4
    decoded = struct.unpack(f"<{EMBEDDING_DIMENSIONS}f", blob)
    assert decoded[0] == 1.5
    assert decoded[383] == -2.25


def test_vector_dimension_mismatch_is_refused() -> None:
    with pytest.raises(IndexLayerError, match="384"):
        serialize_float32_vector([1.0, 2.0, 3.0])
    with pytest.raises(IndexLayerError, match="384"):
        serialize_float32_vector([0.0] * (EMBEDDING_DIMENSIONS + 1))


def test_dependency_errors_name_the_pending_deps_ledger(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The message must point the operator at the tracking file (actionable,
    not a bare stack trace)."""
    monkeypatch.setattr(importlib, "import_module", _blocking_import(("tokenizers",)))
    with pytest.raises(IndexDependencyMissingError, match="pending-deps"):
        BgeSmallOnnxEmbedder(model_dir=tmp_path).embed_batch(["x"])
