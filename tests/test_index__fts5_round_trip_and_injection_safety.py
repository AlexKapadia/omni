"""Real FTS5 round-trip over the 0004 schema + query-syntax injection safety.

Uses the repo's REAL migrations (stdlib sqlite3 FTS5 — no mocks on the BM25
side) against throwaway tmp databases. The injection suite feeds raw FTS5
operator syntax through the sanitiser and the retriever: nothing may crash,
leak rows it shouldn't, or reach FTS5 as syntax.
"""

from pathlib import Path

import aiosqlite
import pytest

from engine.index.hybrid_rrf_retriever import (
    HybridRrfRetriever,
    sanitize_fts_match_query,
)
from engine.storage import apply_migrations, open_sqlite_connection


async def _open_indexed_db(tmp_db_path: Path, real_migrations_dir: Path) -> aiosqlite.Connection:
    await apply_migrations(tmp_db_path, real_migrations_dir)
    return await open_sqlite_connection(tmp_db_path)


async def _insert_chunk(
    connection: aiosqlite.Connection,
    note_path: str,
    contextualized_text: str,
    note_title: str = "T",
    heading_path: str = "",
) -> int:
    cursor = await connection.execute(
        "INSERT INTO chunks (note_path, source_type, note_title, heading_path,"
        " line_start, line_end, char_start, char_end, text, contextualized_text, mtime)"
        " VALUES (?, 'vault', ?, ?, 1, 1, 0, ?, ?, ?, 0.0)",
        (note_path, note_title, heading_path, len(contextualized_text),
         contextualized_text, contextualized_text),
    )
    rowid = int(cursor.lastrowid or 0)
    await cursor.close()
    return rowid


async def _fts_rowids(connection: aiosqlite.Connection, match: str) -> list[int]:
    cursor = await connection.execute(
        "SELECT rowid FROM chunks_fts WHERE chunks_fts MATCH ? ORDER BY bm25(chunks_fts)",
        (match,),
    )
    rows = await cursor.fetchall()
    await cursor.close()
    return [int(r[0]) for r in rows]


async def test_insert_trigger_makes_chunk_searchable(
    tmp_db_path: Path, real_migrations_dir: Path
) -> None:
    connection = await _open_indexed_db(tmp_db_path, real_migrations_dir)
    try:
        rowid = await _insert_chunk(connection, "a.md", "the zebra crossed the road")
        assert await _fts_rowids(connection, '"zebra"') == [rowid]
    finally:
        await connection.close()


async def test_delete_trigger_removes_chunk_from_fts(
    tmp_db_path: Path, real_migrations_dir: Path
) -> None:
    connection = await _open_indexed_db(tmp_db_path, real_migrations_dir)
    try:
        rowid = await _insert_chunk(connection, "a.md", "ephemeral xylophone content")
        assert await _fts_rowids(connection, '"xylophone"') == [rowid]
        await connection.execute("DELETE FROM chunks WHERE id = ?", (rowid,))
        assert await _fts_rowids(connection, '"xylophone"') == []
    finally:
        await connection.close()


async def test_update_trigger_reindexes_new_content(
    tmp_db_path: Path, real_migrations_dir: Path
) -> None:
    connection = await _open_indexed_db(tmp_db_path, real_migrations_dir)
    try:
        rowid = await _insert_chunk(connection, "a.md", "original quokka text")
        await connection.execute(
            "UPDATE chunks SET contextualized_text = ? WHERE id = ?",
            ("replacement wombat text", rowid),
        )
        assert await _fts_rowids(connection, '"quokka"') == []
        assert await _fts_rowids(connection, '"wombat"') == [rowid]
    finally:
        await connection.close()


async def test_bm25_ranks_the_denser_match_first(
    tmp_db_path: Path, real_migrations_dir: Path
) -> None:
    connection = await _open_indexed_db(tmp_db_path, real_migrations_dir)
    try:
        dense = await _insert_chunk(connection, "a.md", "falcon falcon falcon")
        sparse = await _insert_chunk(
            connection, "b.md", "one falcon among many many other unrelated words here"
        )
        assert await _fts_rowids(connection, '"falcon"') == [dense, sparse]
    finally:
        await connection.close()


def test_sanitizer_quotes_every_token_and_or_joins() -> None:
    assert sanitize_fts_match_query("email Priya") == '"email" OR "Priya"'
    assert sanitize_fts_match_query("") == ""
    assert sanitize_fts_match_query("!!! ???") == ""  # no word tokens at all


def test_sanitizer_neutralises_fts5_operator_syntax() -> None:
    """Operators must come out as quoted TERMS (or vanish), never syntax."""
    assert sanitize_fts_match_query('a AND b OR c NOT d') == (
        '"a" OR "AND" OR "b" OR "OR" OR "c" OR "NOT" OR "d"'
    )
    assert sanitize_fts_match_query('title:secret') == '"title" OR "secret"'
    assert sanitize_fts_match_query('"unclosed quote') == '"unclosed" OR "quote"'
    assert sanitize_fts_match_query("NEAR(a b, 5)") == '"NEAR" OR "a" OR "b" OR "5"'
    assert sanitize_fts_match_query("wild*card ^caret") == '"wild" OR "card" OR "caret"'


async def test_adversarial_queries_never_crash_the_retriever(
    tmp_db_path: Path, real_migrations_dir: Path
) -> None:
    """The full FTS5 syntax arsenal through the REAL retriever: no exception,
    and structurally impossible to match content that lacks the tokens."""
    connection = await _open_indexed_db(tmp_db_path, real_migrations_dir)
    try:
        await _insert_chunk(connection, "s.md", "harmless indexed sentence")
        retriever = HybridRrfRetriever(connection, vector_store=None, embedder=None)
        adversarial_queries = [
            '"',
            "'",
            "''; DROP TABLE chunks; --",
            "NEAR(a b, 5)",
            "a AND b OR c NOT d",
            "col:value",
            "((((((",
            "*prefix* suffix*",
            "^first",
            "{weird} [brackets]",
            "\\ backslash \x00 control",
            "🙂 emoji only",
            "你好 世界",
            "-" * 500,
            "MATCH MATCH MATCH",
        ]
        for query in adversarial_queries:
            results = await retriever.retrieve(query)  # must not raise
            for result in results:
                assert result.note_path == "s.md"  # never leaks phantom rows
        # And plain retrieval still works after the abuse:
        hits = await retriever.retrieve("harmless sentence")
        assert [hit.note_path for hit in hits] == ["s.md"]
    finally:
        await connection.close()


async def test_no_word_token_query_returns_empty_not_error(
    tmp_db_path: Path, real_migrations_dir: Path
) -> None:
    connection = await _open_indexed_db(tmp_db_path, real_migrations_dir)
    try:
        await _insert_chunk(connection, "s.md", "content")
        retriever = HybridRrfRetriever(connection, vector_store=None, embedder=None)
        assert await retriever.retrieve("!!!") == []
        assert await retriever.retrieve("") == []
    finally:
        await connection.close()


async def test_unknown_tier_is_refused(
    tmp_db_path: Path, real_migrations_dir: Path
) -> None:
    from engine.index.index_layer_errors import IndexLayerError

    connection = await _open_indexed_db(tmp_db_path, real_migrations_dir)
    try:
        retriever = HybridRrfRetriever(connection, vector_store=None, embedder=None)
        with pytest.raises(IndexLayerError, match="unknown retrieval tier"):
            await retriever.retrieve("q", tier="turbo")
    finally:
        await connection.close()
