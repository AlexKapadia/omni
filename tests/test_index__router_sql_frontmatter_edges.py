"""Router range corners, executor empty/degenerate routes, codec fail-closed.

Targets the branches the main classification-table / round-trip suites leave
uncovered: "this month" / "last year" relative ranges, the empty-name guard
in entity matching, structured lookups that must return [] rather than run
SQL on missing inputs, malformed alias JSON tolerated leniently, and every
fail-closed emit/parse path in the hand-rolled frontmatter codec.
"""

from collections.abc import Mapping
from datetime import date
from pathlib import Path
from typing import Any, cast

import aiosqlite
import pytest

from engine.index.structured_query_router import (
    ROUTE_ENTITY,
    ROUTE_FRONTMATTER,
    ROUTE_TEMPORAL,
    RouteDecision,
    extract_date_range,
    match_entities,
)
from engine.index.structured_sql_lookup_executor import (
    execute_structured_lookup,
    load_known_entities,
)
from engine.storage import apply_migrations, open_sqlite_connection
from engine.vault.frontmatter_codec import (
    emit_frontmatter,
    parse_frontmatter,
    parse_scalar,
)
from engine.vault.vault_errors import FrontmatterFormatError

TODAY = date(2026, 7, 6)  # a Monday in July


# --------------------------------------------------------------------------- #
# Router: relative-range corners + empty-name guard                            #
# --------------------------------------------------------------------------- #


def test_this_month_range_spans_month_start_to_last_day() -> None:
    assert extract_date_range("what changed this month", TODAY) == ("2026-07-01", "2026-07-31")


def test_last_year_range_is_the_full_prior_calendar_year() -> None:
    assert extract_date_range("decisions from last year", TODAY) == ("2025-01-01", "2025-12-31")


def test_empty_entity_name_is_skipped_not_matched() -> None:
    # An empty key must never match (it would otherwise match every query).
    assert match_entities("call priya later", {"": 99, "priya": 1}) == (1,)
    assert match_entities("nothing relevant here", {"": 99}) == ()


# --------------------------------------------------------------------------- #
# Executor: degenerate decisions return [] without touching SQL wrongly        #
# --------------------------------------------------------------------------- #


async def _empty_db(tmp_db_path: Path, real_migrations_dir: Path) -> aiosqlite.Connection:
    await apply_migrations(tmp_db_path, real_migrations_dir)
    return await open_sqlite_connection(tmp_db_path)


async def test_entity_route_without_ids_returns_empty(
    tmp_db_path: Path, real_migrations_dir: Path
) -> None:
    connection = await _empty_db(tmp_db_path, real_migrations_dir)
    try:
        decision = RouteDecision(route=ROUTE_ENTITY, entity_ids=())
        assert await execute_structured_lookup(connection, decision) == []
    finally:
        await connection.close()


async def test_temporal_route_without_range_returns_empty(
    tmp_db_path: Path, real_migrations_dir: Path
) -> None:
    connection = await _empty_db(tmp_db_path, real_migrations_dir)
    try:
        decision = RouteDecision(route=ROUTE_TEMPORAL, date_range=None)
        assert await execute_structured_lookup(connection, decision) == []
    finally:
        await connection.close()


async def test_frontmatter_route_with_missing_field_or_value_returns_empty(
    tmp_db_path: Path, real_migrations_dir: Path
) -> None:
    connection = await _empty_db(tmp_db_path, real_migrations_dir)
    try:
        no_field = RouteDecision(
            route=ROUTE_FRONTMATTER, frontmatter_field=None, frontmatter_value="v"
        )
        no_value = RouteDecision(
            route=ROUTE_FRONTMATTER, frontmatter_field="status", frontmatter_value=None
        )
        assert await execute_structured_lookup(connection, no_field) == []
        assert await execute_structured_lookup(connection, no_value) == []
    finally:
        await connection.close()


async def test_malformed_and_non_list_alias_json_is_tolerated(
    tmp_db_path: Path, real_migrations_dir: Path
) -> None:
    connection = await _empty_db(tmp_db_path, real_migrations_dir)
    try:
        await connection.execute(
            "INSERT INTO entities (id, canonical_name, entity_type, aliases_json)"
            " VALUES (1, 'Priya', 'person', '{not valid json')"
        )
        await connection.execute(
            "INSERT INTO entities (id, canonical_name, entity_type, aliases_json)"
            " VALUES (2, 'Acme', 'company', '\"a bare string\"')"  # valid JSON, not a list
        )
        await connection.execute(
            "INSERT INTO entities (id, canonical_name, entity_type, aliases_json)"
            " VALUES (3, 'Bob', 'person', '[\"Bobby\", 7, \"\"]')"  # mixed list
        )
        known = await load_known_entities(connection)
        # Canonicals always load; only well-formed non-empty string aliases do.
        assert known == {"priya": 1, "acme": 2, "bob": 3, "bobby": 3}
    finally:
        await connection.close()


# --------------------------------------------------------------------------- #
# Frontmatter codec: emit/parse fail-closed corners                            #
# --------------------------------------------------------------------------- #


def test_emit_list_with_non_string_item_fails_closed() -> None:
    fields = cast("Mapping[str, Any]", {"tags": ["ok", 123]})
    with pytest.raises(FrontmatterFormatError, match="only strings"):
        emit_frontmatter(fields)


def test_emit_unsupported_scalar_type_fails_closed() -> None:
    fields = cast("Mapping[str, Any]", {"count": 5})  # int is neither bool/str/list
    with pytest.raises(FrontmatterFormatError, match="unsupported"):
        emit_frontmatter(fields)


def test_unclosed_block_after_a_blank_line_fails_closed() -> None:
    # A blank line inside frontmatter is tolerated, but a fence that never
    # closes must still fail closed rather than silently parse.
    with pytest.raises(FrontmatterFormatError, match="never closed"):
        parse_frontmatter("---\nkey: value\n")


def test_blank_line_inside_frontmatter_is_tolerated() -> None:
    fields, body = parse_frontmatter("---\nkey: value\n\n---\nbody")
    assert fields == {"key": "value"}
    assert body == "body"


def test_unescaped_quote_inside_quoted_scalar_fails_closed() -> None:
    with pytest.raises(FrontmatterFormatError, match="unescaped quote"):
        parse_scalar('"a"b"')
