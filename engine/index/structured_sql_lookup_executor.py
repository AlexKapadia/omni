"""Exact-SQL execution of structured route decisions (entity/temporal/frontmatter).

Purpose: turn a ``RouteDecision`` from the deterministic router into rows
via EXACT SQL over the 0004 schema — the precision path the M3
recommendation puts FIRST for "what's Priya's number" / "what did we agree
in March" style queries. Also hosts the DB loaders that feed the pure
classifier its known entities and frontmatter fields.
Pipeline position: between ``structured_query_router`` (classification)
and the Ask-Omni service; hybrid decisions never reach this module — the
caller sends those to ``hybrid_rrf_retriever``.

Security invariants:
- Every user-derived value (entity ids, dates, frontmatter values) is
  bound as a SQL parameter. The one identifier-position value — the
  frontmatter FIELD name inside a JSON path — is allowlist-validated
  against a strict charset before use (defence in depth on top of the
  router's known-fields check).
- Temporal filters compare ISO-8601 strings (lexicographic == chronological).
"""

import json
import re
from datetime import date

import aiosqlite

from engine.index.chunk_rows_repository import fetch_retrieved_chunks
from engine.index.index_layer_errors import IndexLayerError
from engine.index.retrieved_chunk_types import RetrievedChunk
from engine.index.structured_query_router import (
    ROUTE_ENTITY,
    ROUTE_FRONTMATTER,
    ROUTE_TEMPORAL,
    RouteDecision,
    classify_query,
)

DEFAULT_LOOKUP_LIMIT = 20
_SAFE_FIELD_NAME = re.compile(r"^[a-z_][a-z0-9_-]*$")
# COALESCE(created, modified): a note's temporal anchor is its frontmatter
# date when present, else its modified stamp — documented lookup semantics.
_NOTE_DATE_SQL = "substr(COALESCE(nm.created, nm.modified), 1, 10)"


async def load_known_entities(connection: aiosqlite.Connection) -> dict[str, int]:
    """Lowercased canonical names AND aliases → entity id, for the classifier.

    Alias JSON is untrusted data: non-list / non-string alias payloads are
    skipped, never fatal (lenient read of our own extraction output).
    """
    cursor = await connection.execute("SELECT id, canonical_name, aliases_json FROM entities")
    rows = await cursor.fetchall()
    await cursor.close()
    known: dict[str, int] = {}
    for row in rows:
        entity_id = int(row[0])
        known[str(row[1]).lower()] = entity_id
        try:
            aliases = json.loads(str(row[2]))
        except json.JSONDecodeError:
            continue
        if isinstance(aliases, list):
            for alias in aliases:
                if isinstance(alias, str) and alias:
                    known[alias.lower()] = entity_id
    return known


async def load_known_frontmatter_fields(connection: aiosqlite.Connection) -> frozenset[str]:
    """Distinct lowercased frontmatter keys present across notes_meta."""
    cursor = await connection.execute(
        "SELECT DISTINCT lower(je.key) FROM notes_meta nm, json_each(nm.frontmatter_json) je"
    )
    rows = await cursor.fetchall()
    await cursor.close()
    return frozenset(str(row[0]) for row in rows if row[0])


async def route_structured_query(
    connection: aiosqlite.Connection, query: str, today: date
) -> RouteDecision:
    """Convenience: load classifier inputs from the DB, then classify."""
    return classify_query(
        query,
        await load_known_entities(connection),
        await load_known_frontmatter_fields(connection),
        today,
    )


async def execute_structured_lookup(
    connection: aiosqlite.Connection,
    decision: RouteDecision,
    limit: int = DEFAULT_LOOKUP_LIMIT,
) -> list[RetrievedChunk]:
    """Execute an entity/temporal/frontmatter decision as exact SQL.

    A hybrid decision here is a caller bug — refused loudly (deny by
    default), because silently returning nothing would masquerade as
    "no results found".
    """
    if decision.route == ROUTE_ENTITY:
        return await _entity_lookup(connection, decision, limit)
    if decision.route == ROUTE_TEMPORAL:
        return await _temporal_lookup(connection, decision, limit)
    if decision.route == ROUTE_FRONTMATTER:
        return await _frontmatter_lookup(connection, decision, limit)
    raise IndexLayerError(
        f"route {decision.route!r} is not a structured lookup — send it to the hybrid retriever"
    )


async def _entity_lookup(
    connection: aiosqlite.Connection, decision: RouteDecision, limit: int
) -> list[RetrievedChunk]:
    """Chunks mentioning the matched entities, optionally date-filtered."""
    if not decision.entity_ids:
        return []
    id_marks = ", ".join("?" for _ in decision.entity_ids)
    # Parameter order MUST follow placeholder order in the SQL string: the
    # date placeholders live in the JOIN clause, BEFORE the entity ids.
    parameters: list[object] = []
    date_filter = ""
    if decision.date_range is not None:
        date_filter = (
            " JOIN notes_meta nm ON nm.note_path = c.note_path"
            f" AND {_NOTE_DATE_SQL} BETWEEN ? AND ?"
        )
        parameters.extend(decision.date_range)
    parameters.extend(decision.entity_ids)
    cursor = await connection.execute(
        "SELECT DISTINCT c.id FROM chunks c"  # noqa: S608
        " JOIN entity_mentions em ON em.chunk_id = c.id"
        f"{date_filter} WHERE em.entity_id IN ({id_marks}) ORDER BY c.id LIMIT ?",
        (*parameters, limit),
    )
    chunk_ids = [int(row[0]) for row in await cursor.fetchall()]
    await cursor.close()
    return await fetch_retrieved_chunks(connection, chunk_ids, "structured_entity")


async def _temporal_lookup(
    connection: aiosqlite.Connection, decision: RouteDecision, limit: int
) -> list[RetrievedChunk]:
    """Chunks of notes whose temporal anchor falls in the range, newest first."""
    if decision.date_range is None:
        return []
    cursor = await connection.execute(
        # S608: the only interpolation is _NOTE_DATE_SQL, a static constant;
        # user values (dates, limit) are bound parameters.
        "SELECT c.id FROM chunks c JOIN notes_meta nm ON nm.note_path = c.note_path"  # noqa: S608
        f" WHERE {_NOTE_DATE_SQL} BETWEEN ? AND ?"
        f" ORDER BY {_NOTE_DATE_SQL} DESC, c.id ASC LIMIT ?",
        (*decision.date_range, limit),
    )
    chunk_ids = [int(row[0]) for row in await cursor.fetchall()]
    await cursor.close()
    return await fetch_retrieved_chunks(connection, chunk_ids, "structured_temporal")


async def _frontmatter_lookup(
    connection: aiosqlite.Connection, decision: RouteDecision, limit: int
) -> list[RetrievedChunk]:
    """Chunks of notes whose frontmatter field equals/contains the value.

    Matching is case-insensitive; list-valued fields match when ANY element
    equals the value (json_each also yields a lone scalar, covering both).
    """
    field = decision.frontmatter_field
    value = decision.frontmatter_value
    if not field or value is None:
        return []
    if not _SAFE_FIELD_NAME.match(field):
        # Defence in depth: the field lands in a JSON path (identifier
        # position, unparameterisable) — refuse anything outside the charset.
        raise IndexLayerError(f"frontmatter field {field!r} outside the safe charset")
    json_path = f'$."{field}"'
    cursor = await connection.execute(
        "SELECT c.id FROM chunks c JOIN notes_meta nm ON nm.note_path = c.note_path"
        " WHERE json_type(nm.frontmatter_json, ?) IS NOT NULL"
        " AND EXISTS (SELECT 1 FROM json_each(nm.frontmatter_json, ?) je"
        "             WHERE lower(CAST(je.value AS TEXT)) = lower(?))"
        " ORDER BY c.id LIMIT ?",
        (json_path, json_path, value, limit),
    )
    chunk_ids = [int(row[0]) for row in await cursor.fetchall()]
    await cursor.close()
    return await fetch_retrieved_chunks(connection, chunk_ids, "structured_frontmatter")
