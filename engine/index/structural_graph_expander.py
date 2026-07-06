"""Structural graph expansion: wikilink neighbours + same-entity chunks.

Purpose: the "free structural graph" step of the M3 recommendation —
after hybrid retrieval, pull in chunks from notes the seed results link
to/from (Obsidian's own wikilinks) and chunks sharing an entity with a
seed. Cheap SQL joins; no LLM-built graph (GraphRAG rejected on cost).
Pipeline position: called by ``hybrid_rrf_retriever`` after RRF fusion,
before the (chat-tier) rerank.

Security invariant: all values are bound as parameters; link targets and
note paths are untrusted content and never interpolated into SQL.
"""

from collections.abc import Sequence

import aiosqlite

from engine.index.chunk_rows_repository import fetch_retrieved_chunks
from engine.index.retrieved_chunk_types import RetrievedChunk

GRAPH_EXPANSION_LIMIT = 10  # cap: expansion supplements, never floods, results
RETRIEVAL_SOURCE_GRAPH = "graph_expansion"


async def expand_with_structural_graph(
    connection: aiosqlite.Connection,
    seeds: Sequence[RetrievedChunk],
    limit: int = GRAPH_EXPANSION_LIMIT,
) -> list[RetrievedChunk]:
    """Return up to ``limit`` extra chunks structurally related to the seeds.

    Order (documented, deterministic): wikilink-neighbour chunks first,
    then same-entity chunks; within each class ascending chunk id; seeds
    themselves and duplicates are excluded. Wikilink resolution matches
    ``links.dst_note`` (normalised stem) against ``notes_meta.stem`` —
    unresolved links contribute nothing.
    """
    if not seeds or limit <= 0:
        return []
    seed_ids = sorted({seed.chunk_id for seed in seeds})
    seed_paths = sorted({seed.note_path for seed in seeds})
    id_marks = ", ".join("?" for _ in seed_ids)
    path_marks = ", ".join("?" for _ in seed_paths)

    # Outbound: notes our seeds link to. Inbound: notes linking to our seeds.
    neighbour_sql = (
        "SELECT DISTINCT c.id FROM chunks c WHERE c.note_path IN ("  # noqa: S608
        "  SELECT nm.note_path FROM links l JOIN notes_meta nm ON nm.stem = l.dst_note"
        f"  WHERE l.src_note IN ({path_marks})"
        "  UNION "
        "  SELECT l2.src_note FROM links l2 JOIN notes_meta nm2 ON nm2.stem = l2.dst_note"
        f"  WHERE nm2.note_path IN ({path_marks})"
        f") AND c.id NOT IN ({id_marks}) ORDER BY c.id"
    )
    cursor = await connection.execute(
        neighbour_sql, (*seed_paths, *seed_paths, *seed_ids)
    )
    neighbour_ids = [int(row[0]) for row in await cursor.fetchall()]
    await cursor.close()

    # Same-entity: chunks mentioning any entity a seed chunk mentions.
    entity_sql = (
        "SELECT DISTINCT em2.chunk_id FROM entity_mentions em1"  # noqa: S608
        " JOIN entity_mentions em2 ON em2.entity_id = em1.entity_id"
        f" WHERE em1.chunk_id IN ({id_marks})"
        f" AND em2.chunk_id NOT IN ({id_marks}) ORDER BY em2.chunk_id"
    )
    cursor = await connection.execute(entity_sql, (*seed_ids, *seed_ids))
    entity_ids = [int(row[0]) for row in await cursor.fetchall()]
    await cursor.close()

    combined: list[int] = []
    for chunk_id in [*neighbour_ids, *entity_ids]:
        if chunk_id not in combined:
            combined.append(chunk_id)
        if len(combined) >= limit:
            break
    return await fetch_retrieved_chunks(connection, combined, RETRIEVAL_SOURCE_GRAPH)
