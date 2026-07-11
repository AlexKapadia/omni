"""Incremental indexer: change isolation, deletion, atomicity, transcripts.

Synthetic vaults in tmp_path. Claims: changing ONE note re-chunks only that
note, deletion removes every trace (incl. matching vector-store delete/upsert
calls), and transcripts index from real ``transcript_segments`` rows."""

from collections.abc import Sequence
from pathlib import Path

import aiosqlite
import pytest

from engine.index.index_layer_errors import IndexLayerError
from engine.index.vault_indexer_service import VaultIndexerService
from engine.storage import apply_migrations, open_sqlite_connection


class RecordingVectorStore:
    """VectorStoreProtocol test double recording every call."""

    def __init__(self) -> None:
        self.upserts: list[tuple[int, list[float]]] = []
        self.deletes: list[int] = []

    async def upsert_chunk_embeddings(
        self, pairs: Sequence[tuple[int, Sequence[float]]]
    ) -> None:
        self.upserts.extend((cid, list(vec)) for cid, vec in pairs)

    async def delete_chunk_embeddings(self, chunk_ids: Sequence[int]) -> None:
        self.deletes.extend(chunk_ids)

    async def knn_chunk_ids(
        self, query_embedding: Sequence[float], top_k: int
    ) -> list[tuple[int, float]]:
        return []


class FakeEmbedder:
    """Deterministic 384-dim vectors derived from text length."""

    def embed_batch(self, texts: Sequence[str]) -> list[list[float]]:
        return [[float(len(text))] * 384 for text in texts]


async def _fresh_db(tmp_db_path: Path, real_migrations_dir: Path) -> aiosqlite.Connection:
    await apply_migrations(tmp_db_path, real_migrations_dir)
    return await open_sqlite_connection(tmp_db_path)


def _write_vault(tmp_path: Path) -> tuple[Path, Path, Path]:
    vault = tmp_path / "vault"
    vault.mkdir()
    note_a = vault / "alpha.md"
    note_a.write_text(
        "---\ntitle: Alpha\ndate: 2026-03-01\n---\nAlpha links [[Beta]].\n", encoding="utf-8"
    )
    note_b = vault / "beta.md"
    note_b.write_text("# Beta\nBeta content here.\n", encoding="utf-8")
    return vault, note_a, note_b


async def _chunk_ids(connection: aiosqlite.Connection, note_path: str) -> list[int]:
    cursor = await connection.execute(
        "SELECT id FROM chunks WHERE note_path = ? ORDER BY id", (note_path,)
    )
    ids = [int(r[0]) for r in await cursor.fetchall()]
    await cursor.close()
    return ids


async def test_initial_index_then_noop_rerun(
    tmp_path: Path, tmp_db_path: Path, real_migrations_dir: Path
) -> None:
    connection = await _fresh_db(tmp_db_path, real_migrations_dir)
    try:
        vault, note_a, note_b = _write_vault(tmp_path)
        service = VaultIndexerService(connection, vault)
        first = await service.index_changed_files([note_a, note_b])
        assert (first.indexed_notes, first.unchanged_notes) == (2, 0)
        assert first.chunks_written >= 2
        ids_before = await _chunk_ids(connection, "alpha.md")
        # Unchanged content: nothing re-indexed, chunk ids identical.
        second = await service.index_changed_files([note_a, note_b])
        assert (second.indexed_notes, second.unchanged_notes) == (0, 2)
        assert await _chunk_ids(connection, "alpha.md") == ids_before
    finally:
        await connection.close()


async def test_changing_one_note_touches_only_its_chunks(
    tmp_path: Path, tmp_db_path: Path, real_migrations_dir: Path
) -> None:
    connection = await _fresh_db(tmp_db_path, real_migrations_dir)
    try:
        vault, note_a, note_b = _write_vault(tmp_path)
        service = VaultIndexerService(connection, vault)
        await service.index_changed_files([note_a, note_b])
        alpha_before = await _chunk_ids(connection, "alpha.md")
        beta_before = await _chunk_ids(connection, "beta.md")
        note_a.write_text("---\ntitle: Alpha\n---\nCompletely new text.\n", encoding="utf-8")
        report = await service.index_changed_files([note_a, note_b])
        assert (report.indexed_notes, report.unchanged_notes) == (1, 1)
        alpha_after = await _chunk_ids(connection, "alpha.md")
        assert alpha_after != alpha_before  # delete-then-insert: fresh rows
        assert await _chunk_ids(connection, "beta.md") == beta_before  # untouched
    finally:
        await connection.close()


async def test_deleting_a_note_removes_chunks_links_and_meta(
    tmp_path: Path, tmp_db_path: Path, real_migrations_dir: Path
) -> None:
    connection = await _fresh_db(tmp_db_path, real_migrations_dir)
    try:
        vault, note_a, note_b = _write_vault(tmp_path)
        service = VaultIndexerService(connection, vault)
        await service.index_changed_files([note_a, note_b])
        note_a.unlink()
        report = await service.index_changed_files([note_a])
        assert report.removed_notes == 1
        assert await _chunk_ids(connection, "alpha.md") == []
        for table, column in (("links", "src_note"), ("notes_meta", "note_path")):
            cursor = await connection.execute(
                f"SELECT COUNT(*) FROM {table} WHERE {column} = 'alpha.md'"  # noqa: S608
            )
            row = await cursor.fetchone()
            await cursor.close()
            assert row is not None and row[0] == 0
    finally:
        await connection.close()


async def test_wikilinks_land_normalised_in_links_table(
    tmp_path: Path, tmp_db_path: Path, real_migrations_dir: Path
) -> None:
    connection = await _fresh_db(tmp_db_path, real_migrations_dir)
    try:
        vault, note_a, _note_b = _write_vault(tmp_path)
        service = VaultIndexerService(connection, vault)
        await service.index_changed_files([note_a])
        cursor = await connection.execute("SELECT src_note, dst_note FROM links")
        rows = await cursor.fetchall()
        await cursor.close()
        assert [(str(r[0]), str(r[1])) for r in rows] == [("alpha.md", "beta")]
    finally:
        await connection.close()


async def test_paths_outside_the_vault_root_are_refused(
    tmp_path: Path, tmp_db_path: Path, real_migrations_dir: Path
) -> None:
    connection = await _fresh_db(tmp_db_path, real_migrations_dir)
    try:
        vault, _, _ = _write_vault(tmp_path)
        outside = tmp_path / "outside.md"
        outside.write_text("secret", encoding="utf-8")
        service = VaultIndexerService(connection, vault)
        with pytest.raises(IndexLayerError, match="outside the vault root"):
            await service.index_changed_files([outside])
    finally:
        await connection.close()


async def test_non_markdown_files_are_ignored(
    tmp_path: Path, tmp_db_path: Path, real_migrations_dir: Path
) -> None:
    connection = await _fresh_db(tmp_db_path, real_migrations_dir)
    try:
        vault, _, _ = _write_vault(tmp_path)
        binary = vault / "image.png"
        binary.write_bytes(b"\x89PNG")
        service = VaultIndexerService(connection, vault)
        report = await service.index_changed_files([binary])
        assert report == type(report)()  # all-zero report
    finally:
        await connection.close()


async def test_vector_store_receives_deletes_of_old_and_upserts_of_new_ids(
    tmp_path: Path, tmp_db_path: Path, real_migrations_dir: Path
) -> None:
    connection = await _fresh_db(tmp_db_path, real_migrations_dir)
    try:
        vault, note_a, _ = _write_vault(tmp_path)
        store = RecordingVectorStore()
        service = VaultIndexerService(
            connection, vault, embedder=FakeEmbedder(), vector_store=store
        )
        await service.index_changed_files([note_a])
        first_ids = await _chunk_ids(connection, "alpha.md")
        assert [cid for cid, _ in store.upserts] == first_ids
        assert all(len(vec) == 384 for _, vec in store.upserts)
        store.upserts.clear()
        note_a.write_text("new body entirely\n", encoding="utf-8")
        await service.index_changed_files([note_a])
        assert store.deletes == first_ids  # old embeddings removed
        assert [cid for cid, _ in store.upserts] == await _chunk_ids(connection, "alpha.md")
    finally:
        await connection.close()


async def _seed_meeting(connection: aiosqlite.Connection, meeting_id: str) -> None:
    await connection.execute(
        "INSERT INTO meetings (id, title, started_at) VALUES (?, 'Budget Sync',"
        " '2026-03-02T10:00:00+00:00')",
        (meeting_id,),
    )
    segments = [
        (f"{meeting_id}-s1", "them", "We need the Q3 numbers.", 0.0, 2.0),
        (f"{meeting_id}-s2", "me", "I will send them tomorrow.", 2.0, 4.0),
        (f"{meeting_id}-s3", "them", "Great, thanks.", 4.0, 5.0),
    ]
    for seg_id, stream, text, t_start, t_end in segments:
        await connection.execute(
            "INSERT INTO transcript_segments (id, meeting_id, stream, text, t_start,"
            " t_end, created_at) VALUES (?, ?, ?, ?, ?, ?, '2026-03-02T10:00:00+00:00')",
            (seg_id, meeting_id, stream, text, t_start, t_end),
        )


async def test_transcript_indexes_one_line_per_segment_with_stream_labels(
    tmp_path: Path, tmp_db_path: Path, real_migrations_dir: Path
) -> None:
    connection = await _fresh_db(tmp_db_path, real_migrations_dir)
    try:
        await _seed_meeting(connection, "m-1")
        service = VaultIndexerService(connection, tmp_path / "vault")
        written = await service.index_meeting_transcript("m-1")
        assert written == 1  # short transcript: one chunk
        cursor = await connection.execute(
            "SELECT note_path, source_type, note_title, text, line_start, line_end"
            " FROM chunks WHERE note_path = 'transcript://m-1'"
        )
        row = await cursor.fetchone()
        await cursor.close()
        assert row is not None
        assert (str(row[1]), str(row[2])) == ("transcript", "Budget Sync")
        # One line per segment, Me/Them labels, segment order == line order.
        assert str(row[3]) == (
            "Them: We need the Q3 numbers.\n"
            "Me: I will send them tomorrow.\n"
            "Them: Great, thanks."
        )
        assert (int(row[4]), int(row[5])) == (1, 3)
    finally:
        await connection.close()


async def test_transcript_reindex_replaces_rows_and_unknown_meeting_fails(
    tmp_path: Path, tmp_db_path: Path, real_migrations_dir: Path
) -> None:
    connection = await _fresh_db(tmp_db_path, real_migrations_dir)
    try:
        await _seed_meeting(connection, "m-1")
        service = VaultIndexerService(connection, tmp_path / "vault")
        await service.index_meeting_transcript("m-1")
        before = await _chunk_ids(connection, "transcript://m-1")
        # Occupy the rowid space so a delete-then-insert MUST mint new ids
        # (SQLite reuses max(rowid)+1, so an empty table would alias them).
        await _seed_meeting(connection, "m-2")
        await service.index_meeting_transcript("m-2")
        await service.index_meeting_transcript("m-1")  # finalise again
        after = await _chunk_ids(connection, "transcript://m-1")
        assert len(after) == len(before)
        assert after != before  # delete-then-insert: fresh rows, no UPDATE
        with pytest.raises(IndexLayerError, match="does not exist"):
            await service.index_meeting_transcript("no-such-meeting")
    finally:
        await connection.close()


async def test_meeting_with_zero_segments_removes_stale_transcript_note(
    tmp_path: Path, tmp_db_path: Path, real_migrations_dir: Path
) -> None:
    connection = await _fresh_db(tmp_db_path, real_migrations_dir)
    try:
        await _seed_meeting(connection, "m-1")
        service = VaultIndexerService(connection, tmp_path / "vault")
        await service.index_meeting_transcript("m-1")
        await connection.execute("DELETE FROM transcript_segments WHERE meeting_id = 'm-1'")
        assert await service.index_meeting_transcript("m-1") == 0
        assert await _chunk_ids(connection, "transcript://m-1") == []
    finally:
        await connection.close()


async def test_index_meeting_transcript_skips_soft_deleted_meeting(
    tmp_path: Path, tmp_db_path: Path, real_migrations_dir: Path
) -> None:
    """Reindex must not resurrect transcript:// chunks for soft-deleted meetings."""
    connection = await _fresh_db(tmp_db_path, real_migrations_dir)
    try:
        await _seed_meeting(connection, "m-del")
        service = VaultIndexerService(connection, tmp_path / "vault")
        await service.index_meeting_transcript("m-del")
        assert await _chunk_ids(connection, "transcript://m-del")
        await connection.execute(
            "UPDATE meetings SET deleted_at = '2026-07-10T12:00:00+00:00' WHERE id = 'm-del'"
        )
        await connection.commit()
        assert await service.index_meeting_transcript("m-del") == 0
        assert await _chunk_ids(connection, "transcript://m-del") == []
        cursor = await connection.execute(
            "SELECT COUNT(*) FROM notes_meta WHERE note_path = 'transcript://m-del'"
        )
        assert (await cursor.fetchone())[0] == 0
        await cursor.close()
    finally:
        await connection.close()


async def test_undecodable_bytes_are_replaced_never_fatal(
    tmp_path: Path, tmp_db_path: Path, real_migrations_dir: Path
) -> None:
    connection = await _fresh_db(tmp_db_path, real_migrations_dir)
    try:
        vault, _, _ = _write_vault(tmp_path)
        hostile = vault / "hostile.md"
        hostile.write_bytes(b"valid start \xff\xfe invalid bytes")
        service = VaultIndexerService(connection, vault)
        report = await service.index_changed_files([hostile])
        assert report.indexed_notes == 1  # indexed with replacement chars
    finally:
        await connection.close()
