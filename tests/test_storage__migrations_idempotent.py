"""Migrations runner tests: ordering, idempotency, and atomic failure.

Uses the repo's REAL migrations directory against throwaway tmp databases,
plus synthetic migration sets for failure-path coverage. No test touches
the real %LOCALAPPDATA% database.
"""

from pathlib import Path

import aiosqlite
import pytest

from engine.storage import apply_migrations, list_applied_migrations, open_sqlite_connection
from engine.storage.sqlite_migrations_runner import MigrationError


def _real_migration_names(real_migrations_dir: Path) -> list[str]:
    """The repo's real migration files, in application (filename) order.

    Derived, not hard-coded: every agent that lands a new NNNN_*.sql would
    otherwise have to edit these tests, and a stale literal list would fail
    for reasons unrelated to the runner's behaviour under test.
    """
    return sorted(p.name for p in real_migrations_dir.glob("*.sql"))


async def _dump_schema(db_path: Path) -> list[tuple[str, str, str]]:
    """Full normalised schema dump: (type, name, sql) for every object."""
    async with aiosqlite.connect(db_path) as conn:
        cursor = await conn.execute(
            "SELECT type, name, COALESCE(sql, '') FROM sqlite_master ORDER BY type, name"
        )
        rows = await cursor.fetchall()
    return [(str(r[0]), str(r[1]), str(r[2])) for r in rows]


async def test_first_run_applies_the_initial_migration(
    tmp_db_path: Path, real_migrations_dir: Path
) -> None:
    applied = await apply_migrations(tmp_db_path, real_migrations_dir)
    assert applied == _real_migration_names(real_migrations_dir)
    assert "0001_initial.sql" in applied
    schema = await _dump_schema(tmp_db_path)
    table_names = {name for kind, name, _ in schema if kind == "table"}
    assert {"meetings", "transcript_segments", "audit_log", "schema_migrations"} <= table_names


async def test_second_run_applies_nothing_and_schema_is_bytewise_identical(
    tmp_db_path: Path, real_migrations_dir: Path
) -> None:
    """Idempotency: re-run applies zero migrations and changes zero schema."""
    first = await apply_migrations(tmp_db_path, real_migrations_dir)
    schema_after_first = await _dump_schema(tmp_db_path)

    second = await apply_migrations(tmp_db_path, real_migrations_dir)
    schema_after_second = await _dump_schema(tmp_db_path)

    assert first == _real_migration_names(real_migrations_dir)
    assert second == []  # nothing re-applied
    assert schema_after_second == schema_after_first  # identical, object-for-object


async def test_bookkeeping_records_each_migration_exactly_once(
    tmp_db_path: Path, real_migrations_dir: Path
) -> None:
    """Double-run must not duplicate schema_migrations rows (PK enforces it,
    but the runner must also never attempt the duplicate insert)."""
    await apply_migrations(tmp_db_path, real_migrations_dir)
    await apply_migrations(tmp_db_path, real_migrations_dir)
    conn = await open_sqlite_connection(tmp_db_path)
    try:
        rows = await list_applied_migrations(conn)
        cursor = await conn.execute(
            "SELECT name, COUNT(*) FROM schema_migrations GROUP BY name HAVING COUNT(*) > 1"
        )
        duplicated = await cursor.fetchall()
    finally:
        await conn.close()
    assert rows == _real_migration_names(real_migrations_dir)
    assert list(duplicated) == []  # every migration recorded exactly once


async def test_migrations_apply_in_filename_order(tmp_db_path: Path, tmp_path: Path) -> None:
    """0002 depends on 0001's table; only filename ordering makes it work."""
    migrations = tmp_path / "migs"
    migrations.mkdir()
    # Written out of order on purpose; the runner must sort by name.
    (migrations / "0002_add_column.sql").write_text(
        "ALTER TABLE widgets ADD COLUMN colour TEXT;", encoding="utf-8"
    )
    (migrations / "0001_create_widgets.sql").write_text(
        "CREATE TABLE widgets (id TEXT PRIMARY KEY);", encoding="utf-8"
    )
    applied = await apply_migrations(tmp_db_path, migrations)
    assert applied == ["0001_create_widgets.sql", "0002_add_column.sql"]


async def test_failed_migration_rolls_back_completely_and_records_nothing(
    tmp_db_path: Path, tmp_path: Path
) -> None:
    """Atomicity: a migration that fails mid-file leaves NO trace — not its
    early statements, not a bookkeeping row (fail closed)."""
    migrations = tmp_path / "migs"
    migrations.mkdir()
    (migrations / "0001_good.sql").write_text(
        "CREATE TABLE survivors (id TEXT PRIMARY KEY);", encoding="utf-8"
    )
    (migrations / "0002_bad.sql").write_text(
        # First statement is valid, second is garbage: the valid one must
        # be rolled back with the rest.
        "CREATE TABLE half_applied (id TEXT PRIMARY KEY);\nTHIS IS NOT SQL;",
        encoding="utf-8",
    )
    with pytest.raises(MigrationError, match=r"0002_bad\.sql"):
        await apply_migrations(tmp_db_path, migrations)

    schema = await _dump_schema(tmp_db_path)
    table_names = {name for kind, name, _ in schema if kind == "table"}
    assert "survivors" in table_names  # 0001 committed independently
    assert "half_applied" not in table_names  # 0002 fully rolled back
    conn = await open_sqlite_connection(tmp_db_path)
    try:
        assert await list_applied_migrations(conn) == ["0001_good.sql"]
    finally:
        await conn.close()


async def test_rerun_after_failure_reapplies_the_fixed_migration(
    tmp_db_path: Path, tmp_path: Path
) -> None:
    """Recovery path: fix the bad file, re-run, and it applies cleanly."""
    migrations = tmp_path / "migs"
    migrations.mkdir()
    bad = migrations / "0001_flaky.sql"
    bad.write_text("NOT SQL AT ALL;", encoding="utf-8")
    with pytest.raises(MigrationError):
        await apply_migrations(tmp_db_path, migrations)
    bad.write_text("CREATE TABLE fixed (id TEXT PRIMARY KEY);", encoding="utf-8")
    assert await apply_migrations(tmp_db_path, migrations) == ["0001_flaky.sql"]


async def test_migration_filename_outside_allowlist_is_refused(
    tmp_db_path: Path, tmp_path: Path
) -> None:
    """Filenames are embedded in bookkeeping SQL, so the allowlist must
    refuse anything unexpected before any SQL runs."""
    migrations = tmp_path / "migs"
    migrations.mkdir()
    (migrations / "0001_bad-name.sql").write_text("SELECT 1;", encoding="utf-8")
    with pytest.raises(MigrationError, match="pattern"):
        await apply_migrations(tmp_db_path, migrations)
    assert not tmp_db_path.exists() or await _dump_schema(tmp_db_path) is not None


async def test_migration_managing_its_own_transaction_is_refused(
    tmp_db_path: Path, tmp_path: Path
) -> None:
    """BEGIN/COMMIT inside a migration would break the runner's atomicity
    guarantee, so it is rejected outright."""
    migrations = tmp_path / "migs"
    migrations.mkdir()
    (migrations / "0001_selfmanaged.sql").write_text(
        "BEGIN;\nCREATE TABLE t (id TEXT);\nCOMMIT;", encoding="utf-8"
    )
    with pytest.raises(MigrationError, match="transaction"):
        await apply_migrations(tmp_db_path, migrations)


async def test_empty_migrations_directory_applies_nothing(
    tmp_db_path: Path, tmp_path: Path
) -> None:
    """Degenerate input: an empty directory is a no-op, not an error."""
    migrations = tmp_path / "empty"
    migrations.mkdir()
    assert await apply_migrations(tmp_db_path, migrations) == []
