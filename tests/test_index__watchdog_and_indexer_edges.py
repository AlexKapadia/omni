"""Watchdog event forwarding, indexer error/edge paths, chunker corners.

Watchdog: a fake watchdog module lets us drive the in-function
``_MarkdownEventForwarder`` and prove ONLY markdown file events (not
directory events, not other extensions) reach the callback, with the exact
paths — including a moved event carrying both src and dest.

Indexer: frontmatter-only notes (no chunks) still land notes_meta with the
frontmatter title; transaction failures ROLL BACK leaving no half-note; the
dense sync degrades honestly when the embedder is absent; and removals of
missing notes are true no-ops.
"""

import importlib
import types
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import aiosqlite
import pytest

from engine.index.markdown_heading_aware_chunker import chunk_markdown_note
from engine.index.vault_indexer_service import VaultIndexerService
from engine.index.vault_watchdog_file_watcher import start_vault_file_watcher
from engine.storage import apply_migrations, open_sqlite_connection

# --------------------------------------------------------------------------- #
# Watchdog event forwarding                                                    #
# --------------------------------------------------------------------------- #


class _FakeObserver:
    def __init__(self) -> None:
        self.handler: Any = None
        self.path: str | None = None
        self.recursive: bool | None = None
        self.started = False

    def schedule(self, handler: Any, path: str, recursive: bool) -> None:
        self.handler, self.path, self.recursive = handler, path, recursive

    def start(self) -> None:
        self.started = True


def _install_fake_watchdog(monkeypatch: pytest.MonkeyPatch) -> None:
    real_import = importlib.import_module
    events_mod = types.SimpleNamespace(FileSystemEventHandler=object)
    observers_mod = types.SimpleNamespace(Observer=_FakeObserver)

    def fake_import(name: str, package: str | None = None) -> types.ModuleType:
        if name == "watchdog.observers":
            return observers_mod  # type: ignore[return-value]
        if name == "watchdog.events":
            return events_mod  # type: ignore[return-value]
        return real_import(name, package)

    monkeypatch.setattr(importlib, "import_module", fake_import)


def _event(
    src: str | None = None, dest: str | None = None, is_directory: bool = False
) -> types.SimpleNamespace:
    return types.SimpleNamespace(src_path=src, dest_path=dest, is_directory=is_directory)


def test_watcher_forwards_only_markdown_file_events(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _install_fake_watchdog(monkeypatch)
    received: list[list[Path]] = []
    observer = start_vault_file_watcher(tmp_path, received.append)
    assert observer.started is True
    assert observer.path == str(tmp_path) and observer.recursive is True
    handler = observer.handler

    handler.on_any_event(_event(src=str(tmp_path / "note.md")))  # created/modified/deleted
    assert received[-1] == [tmp_path / "note.md"]
    # A moved event forwards BOTH endpoints when both are markdown.
    handler.on_any_event(
        _event(src=str(tmp_path / "old.md"), dest=str(tmp_path / "new.md"))
    )
    assert received[-1] == [tmp_path / "old.md", tmp_path / "new.md"]
    # Uppercase extension is still markdown (case-insensitive suffix check).
    handler.on_any_event(_event(src=str(tmp_path / "Loud.MD")))
    assert received[-1] == [tmp_path / "Loud.MD"]


def test_watcher_ignores_directories_and_non_markdown(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _install_fake_watchdog(monkeypatch)
    received: list[list[Path]] = []
    handler = start_vault_file_watcher(tmp_path, received.append).handler

    handler.on_any_event(_event(src=str(tmp_path / "sub"), is_directory=True))
    handler.on_any_event(_event(src=str(tmp_path / "image.png")))
    handler.on_any_event(_event(src=str(tmp_path / "data.txt")))
    # A move where only the source is markdown forwards just the .md endpoint.
    handler.on_any_event(_event(src=str(tmp_path / "keep.md"), dest=str(tmp_path / "gone.tmp")))
    assert received == [[tmp_path / "keep.md"]]  # exactly one forwarded event


# --------------------------------------------------------------------------- #
# Indexer error / edge paths                                                   #
# --------------------------------------------------------------------------- #


class _RecordingVectorStore:
    def __init__(self) -> None:
        self.upserts: list[int] = []
        self.deletes: list[int] = []

    async def upsert_chunk_embeddings(
        self, pairs: Sequence[tuple[int, Sequence[float]]]
    ) -> None:
        self.upserts.extend(cid for cid, _ in pairs)

    async def delete_chunk_embeddings(self, chunk_ids: Sequence[int]) -> None:
        self.deletes.extend(chunk_ids)

    async def knn_chunk_ids(
        self, query_embedding: Sequence[float], top_k: int
    ) -> list[tuple[int, float]]:
        return []


class _FakeEmbedder:
    def embed_batch(self, texts: Sequence[str]) -> list[list[float]]:
        return [[float(len(t))] * 384 for t in texts]


class _RaisingConnection:
    """Delegates to a real connection but raises on a chosen SQL fragment,
    letting us prove the indexer's BEGIN/ROLLBACK/raise path fails closed."""

    def __init__(self, real: aiosqlite.Connection, raise_on: str) -> None:
        self._real = real
        self._raise_on = raise_on

    async def execute(self, sql: str, parameters: Any = ()) -> Any:
        if self._raise_on in sql:
            raise RuntimeError("injected DB failure")
        return await self._real.execute(sql, parameters)


async def _fresh_db(tmp_db_path: Path, real_migrations_dir: Path) -> aiosqlite.Connection:
    await apply_migrations(tmp_db_path, real_migrations_dir)
    return await open_sqlite_connection(tmp_db_path)


def _vault(tmp_path: Path) -> Path:
    vault = tmp_path / "vault"
    vault.mkdir()
    return vault


async def _meta_title(connection: aiosqlite.Connection, note_path: str) -> str | None:
    cursor = await connection.execute(
        "SELECT title FROM notes_meta WHERE note_path = ?", (note_path,)
    )
    row = await cursor.fetchone()
    await cursor.close()
    return None if row is None else str(row[0])


async def test_frontmatter_only_note_indexes_meta_with_list_title(
    tmp_path: Path, tmp_db_path: Path, real_migrations_dir: Path
) -> None:
    connection = await _fresh_db(tmp_db_path, real_migrations_dir)
    try:
        vault = _vault(tmp_path)
        listed = vault / "listed.md"
        listed.write_text("---\ntitle:\n  - Primary\n  - Secondary\n---\n", encoding="utf-8")
        empty_title = vault / "empty-title.md"
        empty_title.write_text("---\ntitle: []\n---\n", encoding="utf-8")
        service = VaultIndexerService(connection, vault)
        report = await service.index_changed_files([listed, empty_title])
        assert (report.indexed_notes, report.chunks_written) == (2, 0)  # no body -> no chunks
        # list frontmatter scalar -> first element; empty list -> filename stem.
        assert await _meta_title(connection, "listed.md") == "Primary"
        assert await _meta_title(connection, "empty-title.md") == "empty-title"
    finally:
        await connection.close()


async def test_replace_rows_failure_rolls_back_leaving_no_half_note(
    tmp_path: Path, tmp_db_path: Path, real_migrations_dir: Path
) -> None:
    connection = await _fresh_db(tmp_db_path, real_migrations_dir)
    try:
        vault = _vault(tmp_path)
        note = vault / "n.md"
        note.write_text("# Heading\nBody text here.\n", encoding="utf-8")
        raising = _RaisingConnection(connection, "INSERT OR REPLACE INTO notes_meta")
        service = VaultIndexerService(raising, vault)  # type: ignore[arg-type]
        with pytest.raises(RuntimeError, match="injected DB failure"):
            await service.index_changed_files([note])
        # ROLLBACK undid the DELETEs/INSERTs: nothing committed for this note.
        assert await _meta_title(connection, "n.md") is None
        cursor = await connection.execute("SELECT COUNT(*) FROM chunks WHERE note_path = 'n.md'")
        row = await cursor.fetchone()
        await cursor.close()
        assert row is not None and row[0] == 0
    finally:
        await connection.close()


async def test_remove_failure_rolls_back_and_keeps_the_note(
    tmp_path: Path, tmp_db_path: Path, real_migrations_dir: Path
) -> None:
    connection = await _fresh_db(tmp_db_path, real_migrations_dir)
    try:
        vault = _vault(tmp_path)
        note = vault / "keep.md"
        note.write_text("# Keep\nStays indexed after a failed delete.\n", encoding="utf-8")
        await VaultIndexerService(connection, vault).index_changed_files([note])
        note.unlink()
        raising = _RaisingConnection(connection, "DELETE FROM notes_meta")
        failing_service = VaultIndexerService(raising, vault)  # type: ignore[arg-type]
        with pytest.raises(RuntimeError, match="injected DB failure"):
            await failing_service.index_changed_files([note])
        # Title derives from the filename stem (no frontmatter title); the key
        # assertion is that the row SURVIVED the failed delete (rolled back).
        assert await _meta_title(connection, "keep.md") == "keep"
    finally:
        await connection.close()


async def test_vector_store_present_but_embedder_absent_writes_no_vectors(
    tmp_path: Path, tmp_db_path: Path, real_migrations_dir: Path
) -> None:
    connection = await _fresh_db(tmp_db_path, real_migrations_dir)
    try:
        vault = _vault(tmp_path)
        note = vault / "dense.md"
        note.write_text("# Dense\nHas body so chunks exist.\n", encoding="utf-8")
        store = _RecordingVectorStore()
        service = VaultIndexerService(connection, vault, embedder=None, vector_store=store)
        report = await service.index_changed_files([note])
        assert report.chunks_written >= 1  # chunks landed in SQL
        assert store.upserts == []  # but NO embeddings computed (embedder is None)
        assert store.deletes == []  # first index: no old ids to purge
    finally:
        await connection.close()


async def test_removing_a_never_indexed_note_is_a_true_noop(
    tmp_path: Path, tmp_db_path: Path, real_migrations_dir: Path
) -> None:
    connection = await _fresh_db(tmp_db_path, real_migrations_dir)
    try:
        vault = _vault(tmp_path)
        store = _RecordingVectorStore()
        service = VaultIndexerService(connection, vault, vector_store=store)
        report = await service.index_changed_files([vault / "ghost.md"])  # never existed
        assert report.removed_notes == 0
        assert store.deletes == []  # short-circuits before any vector-store call
    finally:
        await connection.close()


async def test_removing_an_indexed_note_purges_its_embeddings(
    tmp_path: Path, tmp_db_path: Path, real_migrations_dir: Path
) -> None:
    connection = await _fresh_db(tmp_db_path, real_migrations_dir)
    try:
        vault = _vault(tmp_path)
        note = vault / "purge.md"
        note.write_text("# Purge\nBody that produces a chunk.\n", encoding="utf-8")
        store = _RecordingVectorStore()
        service = VaultIndexerService(
            connection, vault, embedder=_FakeEmbedder(), vector_store=store
        )
        await service.index_changed_files([note])
        indexed_ids = list(store.upserts)
        assert indexed_ids  # embeddings were written on index
        note.unlink()
        report = await service.index_changed_files([note])
        assert report.removed_notes == 1
        assert store.deletes == indexed_ids  # exact ids purged from the vector store
    finally:
        await connection.close()


# --------------------------------------------------------------------------- #
# Chunker corners not exercised by the main chunker suite                      #
# --------------------------------------------------------------------------- #


def test_frontmatter_only_note_without_trailing_newline_yields_no_chunks() -> None:
    # Closing fence is the last line (no trailing newline): body starts past
    # the final line, so the body char cursor clamps to end-of-document.
    assert chunk_markdown_note("---\ntitle: Foo\n---", note_path="x.md") == []


def test_list_valued_frontmatter_title_uses_first_element() -> None:
    document = "---\ntitle:\n  - First\n  - Second\n---\n# H\nbody text\n"
    chunks = chunk_markdown_note(document, note_path="note.md")
    assert chunks  # body present -> at least one chunk
    assert chunks[0].note_title == "First"  # list scalar -> first element
