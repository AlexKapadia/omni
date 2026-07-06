"""Router classification table + exact-SQL executor round-trips.

The classifier is pure and deterministic — the table pins every route and
every extracted value against a FIXED ``today`` (2026-07-06, a Monday).
Adversarial rows included: "email Priya about March" is an ACTION (hybrid),
not a temporal/entity lookup, and injection-shaped queries classify without
incident. The executor half runs the real SQL over a real tmp database.
"""

from datetime import date
from pathlib import Path

import aiosqlite
import pytest

from engine.index.index_layer_errors import IndexLayerError
from engine.index.structured_query_router import (
    ROUTE_ENTITY,
    ROUTE_FRONTMATTER,
    ROUTE_HYBRID,
    ROUTE_TEMPORAL,
    RouteDecision,
    classify_query,
    extract_date_range,
)
from engine.index.structured_sql_lookup_executor import (
    execute_structured_lookup,
    load_known_entities,
    load_known_frontmatter_fields,
    route_structured_query,
)
from engine.storage import apply_migrations, open_sqlite_connection

TODAY = date(2026, 7, 6)  # Monday — week arithmetic is asserted exactly
ENTITIES = {"priya sharma": 1, "priya": 1, "acme corp": 2}
FIELDS = frozenset({"status", "tags", "type"})

CLASSIFICATION_TABLE: list[tuple[str, RouteDecision]] = [
    # --- entity lookups ---
    ("What's Priya's number", RouteDecision(route=ROUTE_ENTITY, entity_ids=(1,))),
    ("who is priya sharma", RouteDecision(route=ROUTE_ENTITY, entity_ids=(1,))),
    (
        "meetings with Acme Corp last week",
        RouteDecision(
            route=ROUTE_ENTITY, entity_ids=(2,), date_range=("2026-06-29", "2026-07-05")
        ),
    ),
    # --- temporal ---
    (
        "what did we agree in March",
        RouteDecision(route=ROUTE_TEMPORAL, date_range=("2026-03-01", "2026-03-31")),
    ),
    (
        "notes from yesterday",
        RouteDecision(route=ROUTE_TEMPORAL, date_range=("2026-07-05", "2026-07-05")),
    ),
    (
        "decisions in December",  # future month rolls back to last year
        RouteDecision(route=ROUTE_TEMPORAL, date_range=("2025-12-01", "2025-12-31")),
    ),
    (
        "what happened on 2026-03-02",
        RouteDecision(route=ROUTE_TEMPORAL, date_range=("2026-03-02", "2026-03-02")),
    ),
    (
        "from 2026-01-05 to 2026-02-10",
        RouteDecision(route=ROUTE_TEMPORAL, date_range=("2026-01-05", "2026-02-10")),
    ),
    (
        "commitments in 2025",
        RouteDecision(route=ROUTE_TEMPORAL, date_range=("2025-01-01", "2025-12-31")),
    ),
    (
        "what was agreed in May",  # "may" WITH preposition IS temporal
        RouteDecision(route=ROUTE_TEMPORAL, date_range=("2026-05-01", "2026-05-31")),
    ),
    # --- frontmatter field queries ---
    (
        "status: open",
        RouteDecision(
            route=ROUTE_FRONTMATTER, frontmatter_field="status", frontmatter_value="open"
        ),
    ),
    (
        "tags=projects",
        RouteDecision(
            route=ROUTE_FRONTMATTER, frontmatter_field="tags", frontmatter_value="projects"
        ),
    ),
    # --- hybrid fallthrough (deny nothing) ---
    ("how do we improve the onboarding flow", RouteDecision(route=ROUTE_HYBRID)),
    ("", RouteDecision(route=ROUTE_HYBRID)),
    ("   ", RouteDecision(route=ROUTE_HYBRID)),
    ("may we revisit the budget", RouteDecision(route=ROUTE_HYBRID)),  # "may" = verb
    ("priority: high", RouteDecision(route=ROUTE_HYBRID)),  # unknown field
    ("'; DROP TABLE chunks; --", RouteDecision(route=ROUTE_HYBRID)),  # inert
    # --- ADVERSARIAL: imperative actions are agent work, not lookups ---
    ("email Priya about March", RouteDecision(route=ROUTE_HYBRID)),
    ("Please email Priya about March", RouteDecision(route=ROUTE_HYBRID)),
    ("schedule a call with Acme Corp next week", RouteDecision(route=ROUTE_HYBRID)),
    ("draft a reply to priya sharma", RouteDecision(route=ROUTE_HYBRID)),
]


@pytest.mark.parametrize(("query", "expected"), CLASSIFICATION_TABLE)
def test_classification_table(query: str, expected: RouteDecision) -> None:
    assert classify_query(query, ENTITIES, FIELDS, TODAY) == expected


def test_classifier_is_deterministic() -> None:
    for query, _ in CLASSIFICATION_TABLE:
        first = classify_query(query, ENTITIES, FIELDS, TODAY)
        assert all(
            classify_query(query, ENTITIES, FIELDS, TODAY) == first for _ in range(3)
        )


def test_entity_match_requires_word_boundaries() -> None:
    # "priyanka" must NOT match the entity "priya" (substring != mention).
    decision = classify_query("ask priyanka about it", ENTITIES, FIELDS, TODAY)
    assert decision.route == ROUTE_HYBRID


def test_relative_ranges_anchor_on_injected_today() -> None:
    assert extract_date_range("last week", TODAY) == ("2026-06-29", "2026-07-05")
    assert extract_date_range("this week", TODAY) == ("2026-07-06", "2026-07-12")
    assert extract_date_range("last month", TODAY) == ("2026-06-01", "2026-06-30")
    assert extract_date_range("today", TODAY) == ("2026-07-06", "2026-07-06")
    assert extract_date_range("no dates here", TODAY) is None


async def _seeded_db(tmp_db_path: Path, real_migrations_dir: Path) -> aiosqlite.Connection:
    """Two notes (one dated March, one July), one entity, mentions, chunks."""
    await apply_migrations(tmp_db_path, real_migrations_dir)
    connection = await open_sqlite_connection(tmp_db_path)
    await connection.execute(
        "INSERT INTO entities (id, canonical_name, entity_type, aliases_json)"
        " VALUES (1, 'Priya Sharma', 'person', '[\"Priya\"]')"
    )
    for note_path, created, chunk_id, text in [
        ("march-note.md", "2026-03-05", 11, "Priya agreed to the March budget."),
        ("july-note.md", "2026-07-01", 22, "July planning content."),
    ]:
        await connection.execute(
            "INSERT INTO notes_meta (note_path, source_type, title, stem,"
            " frontmatter_json, created, modified, mtime, content_hash)"
            " VALUES (?, 'vault', ?, ?, ?, ?, ?, 0.0, 'h')",
            (note_path, note_path, note_path[:-3],
             '{"status": "open"}' if note_path.startswith("march") else '{"tags": ["x"]}',
             created, created),
        )
        await connection.execute(
            "INSERT INTO chunks (id, note_path, source_type, note_title, heading_path,"
            " line_start, line_end, char_start, char_end, text, contextualized_text, mtime)"
            " VALUES (?, ?, 'vault', ?, '', 1, 1, 0, ?, ?, ?, 0.0)",
            (chunk_id, note_path, note_path[:-3], len(text), text, text),
        )
    await connection.execute(
        "INSERT INTO entity_mentions (entity_id, chunk_id) VALUES (1, 11)"
    )
    return connection


async def test_loaders_feed_the_classifier_from_the_db(
    tmp_db_path: Path, real_migrations_dir: Path
) -> None:
    connection = await _seeded_db(tmp_db_path, real_migrations_dir)
    try:
        entities = await load_known_entities(connection)
        assert entities == {"priya sharma": 1, "priya": 1}
        fields = await load_known_frontmatter_fields(connection)
        assert fields == frozenset({"status", "tags"})
    finally:
        await connection.close()


async def test_entity_route_executes_to_the_mentioning_chunk(
    tmp_db_path: Path, real_migrations_dir: Path
) -> None:
    connection = await _seeded_db(tmp_db_path, real_migrations_dir)
    try:
        decision = await route_structured_query(connection, "what's Priya's number", TODAY)
        assert decision.route == ROUTE_ENTITY
        results = await execute_structured_lookup(connection, decision)
        assert [r.chunk_id for r in results] == [11]
        assert results[0].retrieval_source == "structured_entity"
        assert results[0].citation == "march-note.md · L1–1"  # noqa: RUF001
    finally:
        await connection.close()


async def test_entity_route_with_date_filter_excludes_out_of_range_notes(
    tmp_db_path: Path, real_migrations_dir: Path
) -> None:
    connection = await _seeded_db(tmp_db_path, real_migrations_dir)
    try:
        in_range = RouteDecision(
            route=ROUTE_ENTITY, entity_ids=(1,), date_range=("2026-03-01", "2026-03-31")
        )
        out_of_range = RouteDecision(
            route=ROUTE_ENTITY, entity_ids=(1,), date_range=("2026-04-01", "2026-04-30")
        )
        assert [r.chunk_id for r in await execute_structured_lookup(connection, in_range)] == [11]
        assert await execute_structured_lookup(connection, out_of_range) == []
    finally:
        await connection.close()


async def test_temporal_route_executes_by_note_date(
    tmp_db_path: Path, real_migrations_dir: Path
) -> None:
    connection = await _seeded_db(tmp_db_path, real_migrations_dir)
    try:
        decision = await route_structured_query(connection, "what did we agree in March", TODAY)
        assert decision.route == ROUTE_TEMPORAL
        results = await execute_structured_lookup(connection, decision)
        assert [r.chunk_id for r in results] == [11]
        assert results[0].retrieval_source == "structured_temporal"
    finally:
        await connection.close()


async def test_frontmatter_route_matches_scalar_and_list_fields(
    tmp_db_path: Path, real_migrations_dir: Path
) -> None:
    connection = await _seeded_db(tmp_db_path, real_migrations_dir)
    try:
        scalar = await route_structured_query(connection, "status: open", TODAY)
        assert scalar.route == ROUTE_FRONTMATTER
        assert [r.chunk_id for r in await execute_structured_lookup(connection, scalar)] == [11]
        # List-valued field: any element matches (case-insensitive).
        list_hit = RouteDecision(
            route=ROUTE_FRONTMATTER, frontmatter_field="tags", frontmatter_value="X"
        )
        assert [r.chunk_id for r in await execute_structured_lookup(connection, list_hit)] == [22]
        miss = RouteDecision(
            route=ROUTE_FRONTMATTER, frontmatter_field="status", frontmatter_value="closed"
        )
        assert await execute_structured_lookup(connection, miss) == []
    finally:
        await connection.close()


async def test_hybrid_decision_is_refused_by_the_executor(
    tmp_db_path: Path, real_migrations_dir: Path
) -> None:
    connection = await _seeded_db(tmp_db_path, real_migrations_dir)
    try:
        with pytest.raises(IndexLayerError, match="hybrid retriever"):
            await execute_structured_lookup(connection, RouteDecision(route=ROUTE_HYBRID))
    finally:
        await connection.close()


async def test_unsafe_frontmatter_field_name_is_refused(
    tmp_db_path: Path, real_migrations_dir: Path
) -> None:
    """Defence in depth: the field lands in a JSON path (identifier
    position) — a hostile field name must be refused, not interpolated."""
    connection = await _seeded_db(tmp_db_path, real_migrations_dir)
    try:
        hostile = RouteDecision(
            route=ROUTE_FRONTMATTER,
            frontmatter_field='x" || (SELECT 1) || "',
            frontmatter_value="v",
        )
        with pytest.raises(IndexLayerError, match="safe charset"):
            await execute_structured_lookup(connection, hostile)
    finally:
        await connection.close()
