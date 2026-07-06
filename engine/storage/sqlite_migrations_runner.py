"""Applies SQL migrations to the engine database, atomically and idempotently.

Purpose: brings any database (fresh or existing) up to the current schema
by applying ``migrations/*.sql`` in filename order, recording each applied
file in ``schema_migrations`` so re-runs apply nothing.
Pipeline position: runs at engine startup before any feature code touches
the database; tests drive it directly against tmp paths.

Security / correctness invariants:
- Each migration + its bookkeeping row commit in ONE transaction: a failed
  migration rolls back completely and is NOT recorded (fail closed — no
  half-applied schema, no lying bookkeeping).
- Migration filenames are validated against a strict allowlist pattern
  before their names are embedded in SQL (untrusted-input discipline, even
  though we author the files ourselves).
"""

import re
from datetime import UTC, datetime
from pathlib import Path

import aiosqlite

from engine.storage.sqlite_connection import open_sqlite_connection

# Allowlist for migration filenames: digits prefix (ordering), safe chars only.
# WHY: names are embedded into the bookkeeping INSERT below; the allowlist
# makes SQL injection via a hostile filename structurally impossible.
_MIGRATION_NAME_PATTERN = re.compile(r"^\d{4}_[a-z0-9_]+\.sql$")

_CREATE_BOOKKEEPING_TABLE = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    name TEXT PRIMARY KEY,
    applied_at TEXT NOT NULL
)
"""


class MigrationError(Exception):
    """Raised when a migration file is malformed or fails to apply."""


async def list_applied_migrations(connection: aiosqlite.Connection) -> list[str]:
    """Return the names of already-applied migrations, in application order."""
    await connection.execute(_CREATE_BOOKKEEPING_TABLE)
    cursor = await connection.execute("SELECT name FROM schema_migrations ORDER BY name")
    rows = await cursor.fetchall()
    await cursor.close()
    return [str(row[0]) for row in rows]


def _discover_migration_files(migrations_dir: Path) -> list[Path]:
    """Find migration files, sorted by filename, validating each name.

    Raises ``MigrationError`` on a name outside the allowlist — a misnamed
    file silently skipped would be worse than a loud failure.
    """
    files = sorted(migrations_dir.glob("*.sql"), key=lambda p: p.name)
    for file in files:
        if not _MIGRATION_NAME_PATTERN.match(file.name):
            raise MigrationError(
                f"migration filename {file.name!r} violates the required "
                "pattern NNNN_snake_case.sql"
            )
    return files


async def apply_migrations(db_path: Path, migrations_dir: Path) -> list[str]:
    """Apply all pending migrations. Returns the names newly applied.

    Idempotent by construction: applied names are recorded in
    ``schema_migrations`` and skipped on subsequent runs.
    """
    connection = await open_sqlite_connection(db_path)
    try:
        applied = set(await list_applied_migrations(connection))
        newly_applied: list[str] = []
        for migration_file in _discover_migration_files(migrations_dir):
            if migration_file.name in applied:
                continue  # Idempotency: already recorded, never re-run.
            await _apply_one_migration(connection, migration_file)
            newly_applied.append(migration_file.name)
        return newly_applied
    finally:
        await connection.close()


async def _apply_one_migration(connection: aiosqlite.Connection, migration_file: Path) -> None:
    """Run one migration file and its bookkeeping row in a single transaction.

    Mechanism: the connection is in autocommit mode, so the composite
    script's explicit BEGIN/COMMIT is the only transaction. If any
    statement fails, we ROLLBACK — schema change and bookkeeping succeed
    or fail together (atomicity invariant). Migration files must therefore
    not contain their own BEGIN/COMMIT.
    """
    sql = migration_file.read_text(encoding="utf-8")
    # Only transaction statements are banned: `BEGIN;` / `BEGIN TRANSACTION` /
    # `COMMIT`. A bare `BEGIN` opening a trigger body (CREATE TRIGGER ...
    # BEGIN <newline>) is legitimate SQL and must NOT trip this guard.
    transaction_statement = re.compile(
        r"^\s*(BEGIN\s*(;|TRANSACTION\b)|COMMIT\b)", flags=re.IGNORECASE | re.MULTILINE
    )
    if transaction_statement.search(sql):
        raise MigrationError(
            f"{migration_file.name}: migrations must not manage their own "
            "transactions; the runner wraps each file in one"
        )
    applied_at = datetime.now(tz=UTC).isoformat()
    # Filename already allowlist-validated (letters/digits/underscore/dot),
    # so embedding it is safe; executescript cannot take parameters.
    composite_script = (
        "BEGIN;\n"
        f"{sql}\n"
        "INSERT INTO schema_migrations (name, applied_at) "
        f"VALUES ('{migration_file.name}', '{applied_at}');\n"
        "COMMIT;"
    )
    try:
        await connection.executescript(composite_script)
    except Exception as exc:
        # Fail closed: leave no open transaction and no bookkeeping row.
        await connection.execute("ROLLBACK")
        raise MigrationError(f"{migration_file.name} failed to apply: {exc}") from exc
