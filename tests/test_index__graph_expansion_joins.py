"""Structural graph expansion: wikilink-neighbour + same-entity SQL joins.

Synthetic three-note graph: a.md --[[b]]--> b.md, plus an entity mentioned
in both a.md's chunk and c.md's chunk. Seeds from a.md must pull in b.md
(outbound link), a.md must be pulled when seeding b.md (inbound link), and
c.md via the shared entity — never the seeds themselves, always capped,
always in the documented deterministic order.
"""

from pathlib import Path

import aiosqlite

from engine.index.chunk_rows_repository import fetch_retrieved_chunks
from engine.index.structural_graph_expander import expand_with_structural_graph
from engine.storage import apply_migrations, open_sqlite_connection

# chunk ids: a.md -> 1, b.md -> 2, c.md -> 3, second b.md chunk -> 4
_NOTES = [("a.md", "a", 1), ("b.md", "b", 2), ("c.md", "c", 3)]


async def _graph_db(tmp_db_path: Path, real_migrations_dir: Path) -> aiosqlite.Connection:
    await apply_migrations(tmp_db_path, real_migrations_dir)
    connection = await open_sqlite_connection(tmp_db_path)
    for note_path, stem, chunk_id in _NOTES:
        await connection.execute(
            "INSERT INTO notes_meta (note_path, source_type, title, stem,"
            " frontmatter_json, created, modified, mtime, content_hash)"
            " VALUES (?, 'vault', ?, ?, '{}', NULL, NULL, 0.0, 'h')",
            (note_path, stem, stem),
        )
        await connection.execute(
            "INSERT INTO chunks (id, note_path, source_type, note_title, heading_path,"
            " line_start, line_end, char_start, char_end, text, contextualized_text, mtime)"
            " VALUES (?, ?, 'vault', ?, '', 1, 1, 0, 4, 'text', 'text', 0.0)",
            (chunk_id, note_path, stem),
        )
    await connection.execute(
        "INSERT INTO chunks (id, note_path, source_type, note_title, heading_path,"
        " line_start, line_end, char_start, char_end, text, contextualized_text, mtime)"
        " VALUES (4, 'b.md', 'vault', 'b', '', 2, 2, 5, 9, 'more', 'more', 0.0)"
    )
    # a.md links to b (normalised stem, as the indexer writes it).
    await connection.execute("INSERT INTO links (src_note, dst_note) VALUES ('a.md', 'b')")
    # Entity 1 is mentioned in a.md's chunk (1) and c.md's chunk (3).
    await connection.execute(
        "INSERT INTO entities (id, canonical_name, entity_type) VALUES (1, 'Priya', 'person')"
    )
    await connection.execute("INSERT INTO entity_mentions (entity_id, chunk_id) VALUES (1, 1)")
    await connection.execute("INSERT INTO entity_mentions (entity_id, chunk_id) VALUES (1, 3)")
    return connection


async def test_outbound_wikilink_then_same_entity_in_documented_order(
    tmp_db_path: Path, real_migrations_dir: Path
) -> None:
    connection = await _graph_db(tmp_db_path, real_migrations_dir)
    try:
        seeds = await fetch_retrieved_chunks(connection, [1], "hybrid_rrf")
        expansion = await expand_with_structural_graph(connection, seeds)
        # Wikilink neighbours (b.md chunks 2, 4) first, then same-entity (3);
        # seed chunk 1 excluded.
        assert [c.chunk_id for c in expansion] == [2, 4, 3]
        assert all(c.retrieval_source == "graph_expansion" for c in expansion)
    finally:
        await connection.close()


async def test_inbound_wikilink_pulls_the_linking_note(
    tmp_db_path: Path, real_migrations_dir: Path
) -> None:
    connection = await _graph_db(tmp_db_path, real_migrations_dir)
    try:
        seeds = await fetch_retrieved_chunks(connection, [2], "hybrid_rrf")
        expansion = await expand_with_structural_graph(connection, seeds)
        # a.md links TO b.md, so seeding b.md pulls a.md's chunk (1) via the
        # inbound edge. b.md's own sibling chunk (4) is NOT expansion — the
        # note is not its own neighbour.
        assert [c.chunk_id for c in expansion] == [1]
    finally:
        await connection.close()


async def test_same_entity_expansion_without_any_links(
    tmp_db_path: Path, real_migrations_dir: Path
) -> None:
    connection = await _graph_db(tmp_db_path, real_migrations_dir)
    try:
        seeds = await fetch_retrieved_chunks(connection, [3], "hybrid_rrf")
        expansion = await expand_with_structural_graph(connection, seeds)
        # c.md has no wikilinks; entity 1 connects its chunk 3 to chunk 1.
        assert [c.chunk_id for c in expansion] == [1]
    finally:
        await connection.close()


async def test_limit_caps_the_expansion(
    tmp_db_path: Path, real_migrations_dir: Path
) -> None:
    connection = await _graph_db(tmp_db_path, real_migrations_dir)
    try:
        seeds = await fetch_retrieved_chunks(connection, [1], "hybrid_rrf")
        capped = await expand_with_structural_graph(connection, seeds, limit=1)
        assert [c.chunk_id for c in capped] == [2]
        assert await expand_with_structural_graph(connection, seeds, limit=0) == []
    finally:
        await connection.close()


async def test_unresolved_link_targets_contribute_nothing(
    tmp_db_path: Path, real_migrations_dir: Path
) -> None:
    connection = await _graph_db(tmp_db_path, real_migrations_dir)
    try:
        await connection.execute(
            "INSERT INTO links (src_note, dst_note) VALUES ('c.md', 'nonexistent note')"
        )
        seeds = await fetch_retrieved_chunks(connection, [3], "hybrid_rrf")
        expansion = await expand_with_structural_graph(connection, seeds)
        assert [c.chunk_id for c in expansion] == [1]  # entity edge only
    finally:
        await connection.close()


async def test_empty_seeds_expand_to_nothing(
    tmp_db_path: Path, real_migrations_dir: Path
) -> None:
    connection = await _graph_db(tmp_db_path, real_migrations_dir)
    try:
        assert await expand_with_structural_graph(connection, []) == []
    finally:
        await connection.close()
