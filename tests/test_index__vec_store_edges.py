"""SqliteVecStore over a REAL sqlite-vec (vec0) tmp database.

sqlite-vec is a real runtime dep and loads in-process, so these tests
exercise the actual vec0 KNN path (not a mock): exact ids + distances in
distance order, delete-then-insert upsert replacement (no duplicate rows),
missing-id deletes as no-ops, and fail-closed dimension checks. Every
assertion pins an exact row set / ordering so a wrong query would fail.
"""

from pathlib import Path

import pytest

from engine.index.bge_small_onnx_embedder import EMBEDDING_DIMENSIONS
from engine.index.index_layer_errors import IndexLayerError
from engine.index.sqlite_vec_store import SqliteVecStore
from engine.storage import apply_migrations, open_sqlite_connection


def _unit(dimension: int, value: float = 1.0) -> list[float]:
    """A 384-vector that is ``value`` on one axis and 0 elsewhere."""
    vector = [0.0] * EMBEDDING_DIMENSIONS
    vector[dimension] = value
    return vector


async def _open_store(tmp_db_path: Path, real_migrations_dir: Path) -> SqliteVecStore:
    await apply_migrations(tmp_db_path, real_migrations_dir)
    connection = await open_sqlite_connection(tmp_db_path)
    return SqliteVecStore(connection)


async def _row_count(store: SqliteVecStore) -> int:
    cursor = await store._connection.execute("SELECT COUNT(*) FROM chunks_vec")
    row = await cursor.fetchone()
    await cursor.close()
    assert row is not None
    return int(row[0])


async def test_knn_returns_exact_ids_and_distances_in_distance_order(
    tmp_db_path: Path, real_migrations_dir: Path
) -> None:
    store = await _open_store(tmp_db_path, real_migrations_dir)
    try:
        # id 1 == query (distance 0), id 2 close on same axis, id 3 orthogonal.
        await store.upsert_chunk_embeddings(
            [(1, _unit(0, 1.0)), (2, _unit(0, 0.9)), (3, _unit(1, 1.0))]
        )
        results = await store.knn_chunk_ids(_unit(0, 1.0), top_k=2)
        assert [cid for cid, _ in results] == [1, 2]  # nearest first, id 3 excluded
        assert results[0][1] == 0.0  # identical float32 bits => exact zero distance
        assert abs(results[1][1] - 0.1) < 1e-4  # |1.0 - 0.9|
        # types are plain int/float, not sqlite Row objects
        assert all(isinstance(cid, int) and isinstance(dist, float) for cid, dist in results)
    finally:
        await store._connection.close()


async def test_upsert_replaces_in_place_without_duplicating_rows(
    tmp_db_path: Path, real_migrations_dir: Path
) -> None:
    store = await _open_store(tmp_db_path, real_migrations_dir)
    try:
        await store.upsert_chunk_embeddings([(1, _unit(0)), (2, _unit(1)), (3, _unit(2))])
        assert await _row_count(store) == 3
        # Re-upsert id 1 moving it far from the axis-0 query.
        await store.upsert_chunk_embeddings([(1, _unit(3, 5.0))])
        assert await _row_count(store) == 3  # replaced, NOT inserted as a 4th row
        results = await store.knn_chunk_ids(_unit(0), top_k=3)
        # id 1 is now the farthest from the axis-0 query, so it sorts last.
        assert results[0][0] != 1
        assert results[-1][0] == 1
    finally:
        await store._connection.close()


async def test_delete_removes_only_named_ids_and_missing_ids_are_noops(
    tmp_db_path: Path, real_migrations_dir: Path
) -> None:
    store = await _open_store(tmp_db_path, real_migrations_dir)
    try:
        await store.upsert_chunk_embeddings([(1, _unit(0)), (2, _unit(1))])
        # Deleting a never-inserted id must not raise and must not change rows.
        await store.delete_chunk_embeddings([999])
        assert await _row_count(store) == 2
        await store.delete_chunk_embeddings([1])
        assert await _row_count(store) == 1
        results = await store.knn_chunk_ids(_unit(0), top_k=5)
        assert [cid for cid, _ in results] == [2]  # id 1 gone, id 2 remains
    finally:
        await store._connection.close()


async def test_empty_upsert_and_empty_delete_still_create_schema_and_noop(
    tmp_db_path: Path, real_migrations_dir: Path
) -> None:
    store = await _open_store(tmp_db_path, real_migrations_dir)
    try:
        await store.upsert_chunk_embeddings([])  # ensures schema, writes nothing
        await store.delete_chunk_embeddings([])
        assert await _row_count(store) == 0
        # schema_ready short-circuit: a later real query works without re-loading.
        assert await store.knn_chunk_ids(_unit(0), top_k=1) == []
    finally:
        await store._connection.close()


async def test_wrong_dimension_vectors_fail_closed_on_write_and_query(
    tmp_db_path: Path, real_migrations_dir: Path
) -> None:
    store = await _open_store(tmp_db_path, real_migrations_dir)
    try:
        with pytest.raises(IndexLayerError, match="384"):
            await store.upsert_chunk_embeddings([(1, [0.0] * (EMBEDDING_DIMENSIONS - 1))])
        with pytest.raises(IndexLayerError, match="384"):
            await store.knn_chunk_ids([], top_k=1)  # empty vector is a dim mismatch
        assert await _row_count(store) == 0  # nothing poisoned the table
    finally:
        await store._connection.close()
