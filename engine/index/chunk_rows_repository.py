"""Loads ``chunks`` rows by id into ``RetrievedChunk`` results.

Purpose: the one place a chunk id becomes a fully-cited ``RetrievedChunk``
— every retrieval path (hybrid, graph expansion, structured SQL) funnels
through here, so the citation fields are populated identically everywhere.
Pipeline position: called by ``hybrid_rrf_retriever``,
``structural_graph_expander``, and ``structured_sql_lookup_executor``.

Security invariant: chunk ids are integers bound as SQL parameters (the
placeholder list is built from ``?`` only) — untrusted text never reaches
the SQL string.
"""

from collections.abc import Mapping, Sequence

import aiosqlite

from engine.index.retrieved_chunk_types import RetrievedChunk

_CHUNK_COLUMNS = (
    "id, note_path, source_type, note_title, heading_path, "
    "line_start, line_end, text, contextualized_text"
)


async def fetch_retrieved_chunks(
    connection: aiosqlite.Connection,
    chunk_ids: Sequence[int],
    retrieval_source: str,
    scores: Mapping[int, float] | None = None,
) -> list[RetrievedChunk]:
    """Load chunk rows preserving the order of ``chunk_ids``.

    Ids not present in the table are silently absent from the result (the
    caller's ranking may reference chunks deleted by a concurrent re-index;
    returning fewer results is honest, inventing rows is not).
    """
    if not chunk_ids:
        return []
    placeholders = ", ".join("?" for _ in chunk_ids)  # parameterised, ints only
    cursor = await connection.execute(
        f"SELECT {_CHUNK_COLUMNS} FROM chunks WHERE id IN ({placeholders})",  # noqa: S608
        tuple(int(chunk_id) for chunk_id in chunk_ids),
    )
    rows = await cursor.fetchall()
    await cursor.close()
    by_id = {int(row[0]): row for row in rows}
    results: list[RetrievedChunk] = []
    for chunk_id in chunk_ids:
        row = by_id.get(int(chunk_id))
        if row is None:
            continue
        results.append(
            RetrievedChunk(
                chunk_id=int(row[0]),
                note_path=str(row[1]),
                source_type=str(row[2]),
                note_title=str(row[3]),
                heading_path=str(row[4]),
                line_start=int(row[5]),
                line_end=int(row[6]),
                text=str(row[7]),
                contextualized_text=str(row[8]),
                score=float(scores.get(int(chunk_id), 0.0)) if scores else 0.0,
                retrieval_source=retrieval_source,
            )
        )
    return results
