"""Incremental vault + transcript indexer: the write side of the M3 index.

Purpose: keeps the 0004 index tables in lockstep with the user's vault
markdown and finalised meeting transcripts. Incremental by content hash;
re-indexing a note is DELETE-THEN-INSERT in one transaction — the index
is never half-a-note (atomicity invariant).
Pipeline position: fed by the vault file watcher (wiring later) and by
meeting finalisation; writes ``chunks`` (FTS5 follows via the 0004
triggers), ``notes_meta``, ``links``, and the vector store.

Security / correctness invariants:
- Local-only: everything indexed stays in the local SQLite file.
- Note content is UNTRUSTED DATA: parameterised SQL only; undecodable
  bytes replaced, never fatal; markdown inside transcript speech is inert
  text (a spoken "# heading" can only mis-label its own breadcrumb).
- Paths outside the vault root are REFUSED (deny by default), not skipped.
- Dense embeddings are written AFTER the chunk transaction commits; an
  absent embedder/vector store (deps pending) is an explicit degradation.

Transcript citations: pseudo-note ``transcript://<meeting_id>`` has one
``Me:``/``Them:`` line per segment — cited line N == segment N.
"""

import asyncio
import hashlib
import json
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import aiosqlite

from engine.index.bge_small_onnx_embedder import EmbedderProtocol
from engine.index.index_layer_errors import IndexLayerError
from engine.index.markdown_heading_aware_chunker import Chunk, chunk_markdown_note
from engine.index.sqlite_vec_store import VectorStoreProtocol
from engine.index.wikilink_and_frontmatter_parser import parse_note

TRANSCRIPT_NOTE_PATH_PREFIX = "transcript://"


@dataclass(frozen=True)
class IndexingReport:
    """What one incremental pass actually did (honest accounting)."""

    indexed_notes: int = 0
    unchanged_notes: int = 0
    removed_notes: int = 0
    chunks_written: int = 0


class VaultIndexerService:
    """Incremental indexer over one aiosqlite connection (0004 schema applied)."""

    def __init__(
        self,
        connection: aiosqlite.Connection,
        vault_root: Path,
        embedder: EmbedderProtocol | None = None,
        vector_store: VectorStoreProtocol | None = None,
    ) -> None:
        self._connection = connection
        self._vault_root = vault_root.resolve()
        self._embedder = embedder
        self._vector_store = vector_store

    async def index_changed_files(self, changed_paths: Iterable[Path]) -> IndexingReport:
        """Re-index changed notes, remove deleted ones, skip unchanged ones.

        Change detection: sha256 of the file content (mtime is stored for
        observability but the HASH decides — editors and sync clients lie
        about mtimes). Non-markdown files are ignored.
        """
        indexed = unchanged = removed = chunks_written = 0
        for path in changed_paths:
            resolved = path.resolve()
            try:
                note_path = resolved.relative_to(self._vault_root).as_posix()
            except ValueError as exc:  # deny by default: never index outside the vault
                raise IndexLayerError(f"{resolved} is outside the vault root") from exc
            if resolved.suffix.lower() != ".md":
                continue
            if not resolved.is_file():
                removed += await self._remove_note(note_path)
                continue
            # Untrusted bytes: replace undecodable sequences, never crash.
            document = resolved.read_text(encoding="utf-8", errors="replace")
            content_hash = hashlib.sha256(document.encode("utf-8")).hexdigest()
            if await self._is_unchanged(note_path, content_hash):
                unchanged += 1
                continue
            mtime = resolved.stat().st_mtime
            count = await self._reindex_note(note_path, document, mtime, content_hash)
            indexed += 1
            chunks_written += count
        return IndexingReport(indexed, unchanged, removed, chunks_written)

    async def index_meeting_transcript(self, meeting_id: str) -> int:
        """Index a finalised meeting's transcript; returns chunks written.

        One line per segment (``Me:``/``Them:`` prefix), ordered by start
        time — line numbers in citations are segment ordinals. A meeting
        with no segments removes any stale transcript note and writes 0.
        """
        cursor = await self._connection.execute(
            "SELECT title, started_at FROM meetings WHERE id = ?", (meeting_id,)
        )
        meeting = await cursor.fetchone()
        await cursor.close()
        if meeting is None:  # fail closed: an unknown meeting is a caller bug
            raise IndexLayerError(f"meeting {meeting_id!r} does not exist")
        cursor = await self._connection.execute(
            "SELECT stream, text FROM transcript_segments"
            " WHERE meeting_id = ? ORDER BY t_start, id",
            (meeting_id,),
        )
        segments = await cursor.fetchall()
        await cursor.close()
        note_path = f"{TRANSCRIPT_NOTE_PATH_PREFIX}{meeting_id}"
        if not segments:
            await self._remove_note(note_path)
            return 0
        document = "\n".join(
            f"{'Me' if str(row[0]) == 'me' else 'Them'}: {row[1]}" for row in segments
        )
        title = str(meeting[0])
        started_date = str(meeting[1])[:10]
        chunks = chunk_markdown_note(
            document,
            note_path=note_path,
            source_type="transcript",
            note_title=title,
            note_date=started_date,
        )
        frontmatter_json = json.dumps({"type": "transcript", "date": started_date})
        await self._replace_note_rows(
            note_path=note_path,
            source_type="transcript",
            title=title,
            stem=meeting_id.lower(),
            frontmatter_json=frontmatter_json,
            created=started_date,
            modified=started_date,
            mtime=0.0,
            content_hash=hashlib.sha256(document.encode("utf-8")).hexdigest(),
            chunks=chunks,
            link_targets=[],
        )
        return len(chunks)

    async def _is_unchanged(self, note_path: str, content_hash: str) -> bool:
        cursor = await self._connection.execute(
            "SELECT content_hash FROM notes_meta WHERE note_path = ?", (note_path,)
        )
        row = await cursor.fetchone()
        await cursor.close()
        return row is not None and str(row[0]) == content_hash

    async def _reindex_note(
        self, note_path: str, document: str, mtime: float, content_hash: str
    ) -> int:
        """Chunk + parse one vault note and replace all its index rows."""
        parsed = parse_note(document)
        chunks = chunk_markdown_note(document, note_path=note_path, source_type="vault")
        stem = note_path.rsplit("/", 1)[-1]
        stem = stem[:-3].lower() if stem.lower().endswith(".md") else stem.lower()
        if chunks:
            title = chunks[0].note_title
        else:  # frontmatter-only note: no chunks, but notes_meta still lands
            title = _frontmatter_scalar(parsed.frontmatter, "title") or stem
        created = _frontmatter_scalar(parsed.frontmatter, "date") or _frontmatter_scalar(
            parsed.frontmatter, "created"
        )
        modified = _frontmatter_scalar(parsed.frontmatter, "modified") or (
            datetime.fromtimestamp(mtime, tz=UTC).date().isoformat()
        )
        # Targets: alias/#heading stripped by the parser; lowercased to match stem.
        link_targets = sorted({link.target.lower() for link in parsed.wikilinks})
        await self._replace_note_rows(
            note_path=note_path,
            source_type="vault",
            title=title,
            stem=stem,
            frontmatter_json=json.dumps(parsed.frontmatter, ensure_ascii=False),
            created=created,
            modified=modified,
            mtime=mtime,
            content_hash=content_hash,
            chunks=chunks,
            link_targets=link_targets,
        )
        return len(chunks)

    async def _replace_note_rows(
        self,
        note_path: str,
        source_type: str,
        title: str,
        stem: str,
        frontmatter_json: str,
        created: str | None,
        modified: str | None,
        mtime: float,
        content_hash: str,
        chunks: list[Chunk],
        link_targets: list[str],
    ) -> None:
        """Delete-then-insert every row for one note, atomically; then the
        post-commit vector-store sync (see module docstring)."""
        old_chunk_ids = await self._chunk_ids_for_note(note_path)
        await self._connection.execute("BEGIN IMMEDIATE")
        try:
            await self._connection.execute("DELETE FROM chunks WHERE note_path = ?", (note_path,))
            await self._connection.execute("DELETE FROM links WHERE src_note = ?", (note_path,))
            await self._connection.execute(
                "INSERT OR REPLACE INTO notes_meta (note_path, source_type, title, stem,"
                " frontmatter_json, created, modified, mtime, content_hash)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (note_path, source_type, title, stem, frontmatter_json, created, modified,
                 mtime, content_hash),
            )
            new_chunk_ids: list[int] = []
            for chunk in chunks:
                cursor = await self._connection.execute(
                    "INSERT INTO chunks (note_path, source_type, note_title, heading_path,"
                    " line_start, line_end, char_start, char_end, text, contextualized_text,"
                    " mtime) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (chunk.note_path, chunk.source_type, chunk.note_title, chunk.heading_path,
                     chunk.line_start, chunk.line_end, chunk.char_start, chunk.char_end,
                     chunk.text, chunk.contextualized_text, mtime),
                )
                new_chunk_ids.append(int(cursor.lastrowid or 0))
                await cursor.close()
            for target in link_targets:
                await self._connection.execute(
                    "INSERT OR IGNORE INTO links (src_note, dst_note) VALUES (?, ?)",
                    (note_path, target),
                )
            await self._connection.execute("COMMIT")
        except Exception:
            await self._connection.execute("ROLLBACK")  # fail closed: no half-note
            raise
        await self._sync_vector_store(old_chunk_ids, new_chunk_ids, chunks)

    async def _sync_vector_store(
        self, old_chunk_ids: list[int], new_chunk_ids: list[int], chunks: list[Chunk]
    ) -> None:
        """Post-commit dense sync; a no-op when dense is not configured."""
        if self._vector_store is None:
            return
        await self._vector_store.delete_chunk_embeddings(old_chunk_ids)
        if self._embedder is None or not chunks:
            return
        texts = [chunk.contextualized_text for chunk in chunks]
        vectors = await asyncio.to_thread(self._embedder.embed_batch, texts)
        await self._vector_store.upsert_chunk_embeddings(
            list(zip(new_chunk_ids, vectors, strict=True))
        )

    async def _chunk_ids_for_note(self, note_path: str) -> list[int]:
        cursor = await self._connection.execute(
            "SELECT id FROM chunks WHERE note_path = ?", (note_path,)
        )
        ids = [int(row[0]) for row in await cursor.fetchall()]
        await cursor.close()
        return ids

    async def _remove_note(self, note_path: str) -> int:
        """Remove every index row for one note; returns 1 if it existed."""
        old_chunk_ids = await self._chunk_ids_for_note(note_path)
        cursor = await self._connection.execute(
            "SELECT 1 FROM notes_meta WHERE note_path = ?", (note_path,)
        )
        existed = await cursor.fetchone() is not None
        await cursor.close()
        if not existed and not old_chunk_ids:
            return 0
        await self._connection.execute("BEGIN IMMEDIATE")
        try:
            await self._connection.execute("DELETE FROM chunks WHERE note_path = ?", (note_path,))
            await self._connection.execute("DELETE FROM links WHERE src_note = ?", (note_path,))
            await self._connection.execute(
                "DELETE FROM notes_meta WHERE note_path = ?", (note_path,)
            )
            await self._connection.execute("COMMIT")
        except Exception:
            await self._connection.execute("ROLLBACK")
            raise
        if self._vector_store is not None:
            await self._vector_store.delete_chunk_embeddings(old_chunk_ids)
        return 1


def _frontmatter_scalar(frontmatter: dict[str, str | list[str]], key: str) -> str | None:
    """First scalar value of a lenient frontmatter field, or None."""
    value = frontmatter.get(key)
    if isinstance(value, list):
        return value[0] if value else None
    return value
