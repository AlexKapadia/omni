"""sqlite-vec (vec0) vector store for chunk embeddings + KNN queries.

Purpose: the dense side's storage — one 384-dim float32 embedding per
chunk in a ``chunks_vec`` vec0 virtual table, queried by KNN at retrieval
time. Entirely in-process SQLite: no server, nothing leaves the machine
(local-only invariant).
Pipeline position: written by the vault indexer after chunk rows commit;
read by the hybrid retriever (dense top-50).

Why the table is created HERE and not in migrations/0004: vec0 requires
the sqlite-vec loadable extension, which the migrations runner's plain
connection does not load. ``ensure_vec_schema`` is idempotent
(CREATE ... IF NOT EXISTS) and runs at store init instead.

Dependency (LAZY, fail closed): ``sqlite-vec`` is a pending dependency
(docs/progress/pending-deps.txt), imported via ``importlib`` at first use;
absence raises a clear ``IndexDependencyMissingError``. Unit tests mock at
the ``VectorStoreProtocol`` boundary. PACKAGING NOTE: the sqlite-vec
loadable extension (vec0.dll) must ship inside the PyInstaller bundle —
tracked for the packaging manifest.

Vector encoding: vec0 accepts little-endian float32 blobs; we pack with
``struct`` so serialisation needs no third-party code.
"""

import importlib
import struct
from collections.abc import Sequence
from typing import Any, Protocol

import aiosqlite

from engine.index.bge_small_onnx_embedder import EMBEDDING_DIMENSIONS
from engine.index.index_layer_errors import IndexDependencyMissingError, IndexLayerError


class VectorStoreProtocol(Protocol):
    """Mockable vector-store boundary used by the indexer and retriever."""

    async def upsert_chunk_embeddings(
        self, pairs: Sequence[tuple[int, Sequence[float]]]
    ) -> None:
        """Insert-or-replace (chunk_id, embedding) rows."""
        ...

    async def delete_chunk_embeddings(self, chunk_ids: Sequence[int]) -> None:
        """Remove embeddings for deleted chunks."""
        ...

    async def knn_chunk_ids(
        self, query_embedding: Sequence[float], top_k: int
    ) -> list[tuple[int, float]]:
        """K nearest chunk ids with distances, best (smallest) first."""
        ...


def serialize_float32_vector(vector: Sequence[float]) -> bytes:
    """Pack a vector as the little-endian float32 blob vec0 expects.

    Fails closed on a dimension mismatch — a wrong-sized vector silently
    stored would poison every subsequent KNN result.
    """
    if len(vector) != EMBEDDING_DIMENSIONS:
        raise IndexLayerError(
            f"embedding has {len(vector)} dimensions; expected {EMBEDDING_DIMENSIONS}"
        )
    return struct.pack(f"<{EMBEDDING_DIMENSIONS}f", *vector)


class SqliteVecStore:
    """chunks_vec vec0 table wiring over an existing aiosqlite connection."""

    def __init__(self, connection: aiosqlite.Connection) -> None:
        self._connection = connection
        self._schema_ready = False

    async def ensure_vec_schema(self) -> None:
        """Load the sqlite-vec extension and create chunks_vec, idempotently."""
        if self._schema_ready:
            return
        try:
            # importlib (not a static import): sqlite-vec is a PENDING dep —
            # see docs/progress/pending-deps.txt — so a static import would
            # trip strict mypy before the orchestrator lands it.
            sqlite_vec: Any = importlib.import_module("sqlite_vec")
        except ImportError as exc:
            raise IndexDependencyMissingError(
                "the 'sqlite-vec' package is required for dense retrieval but "
                "is not installed — tracked in docs/progress/pending-deps.txt."
            ) from exc
        # Loadable extensions are disabled by default in Python's sqlite3;
        # enable only long enough to load vec0, then disable again (least
        # privilege: no other code path may load extensions).
        await self._connection.enable_load_extension(True)
        try:
            await self._connection.load_extension(sqlite_vec.loadable_path())
        finally:
            await self._connection.enable_load_extension(False)
        await self._connection.execute(
            "CREATE VIRTUAL TABLE IF NOT EXISTS chunks_vec USING vec0("
            f"chunk_id INTEGER PRIMARY KEY, embedding float[{EMBEDDING_DIMENSIONS}])"
        )
        self._schema_ready = True

    async def upsert_chunk_embeddings(
        self, pairs: Sequence[tuple[int, Sequence[float]]]
    ) -> None:
        """Delete-then-insert per chunk_id (vec0 has no ON CONFLICT), idempotent."""
        await self.ensure_vec_schema()
        for chunk_id, vector in pairs:
            blob = serialize_float32_vector(vector)
            await self._connection.execute(
                "DELETE FROM chunks_vec WHERE chunk_id = ?", (chunk_id,)
            )
            await self._connection.execute(
                "INSERT INTO chunks_vec (chunk_id, embedding) VALUES (?, ?)",
                (chunk_id, blob),
            )

    async def delete_chunk_embeddings(self, chunk_ids: Sequence[int]) -> None:
        """Remove embeddings for the given chunk ids (missing ids are no-ops)."""
        await self.ensure_vec_schema()
        for chunk_id in chunk_ids:
            await self._connection.execute(
                "DELETE FROM chunks_vec WHERE chunk_id = ?", (chunk_id,)
            )

    async def knn_chunk_ids(
        self, query_embedding: Sequence[float], top_k: int
    ) -> list[tuple[int, float]]:
        """vec0 KNN: smallest distance first. Parameterised throughout."""
        await self.ensure_vec_schema()
        blob = serialize_float32_vector(query_embedding)
        cursor = await self._connection.execute(
            "SELECT chunk_id, distance FROM chunks_vec "
            "WHERE embedding MATCH ? AND k = ? ORDER BY distance",
            (blob, top_k),
        )
        rows = await cursor.fetchall()
        await cursor.close()
        return [(int(row[0]), float(row[1])) for row in rows]
