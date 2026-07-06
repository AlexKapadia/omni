"""Audit-log append-only tests: the schema triggers must actually abort.

Security invariant under test (claude.md §5.6): the audit trail is
tamper-evident because UPDATE and DELETE are blocked by RAISE(ABORT)
triggers in the schema itself. These tests attack the table directly and
assert the triggers fire AND the data survives untouched.
"""

import sqlite3
from pathlib import Path

import aiosqlite
import pytest

from engine.storage import apply_migrations, open_sqlite_connection


async def _migrated_connection(
    tmp_db_path: Path, real_migrations_dir: Path
) -> aiosqlite.Connection:
    """A connection to a freshly migrated throwaway database."""
    await apply_migrations(tmp_db_path, real_migrations_dir)
    return await open_sqlite_connection(tmp_db_path)


async def _insert_audit_row(conn: aiosqlite.Connection, action: str = "test.action") -> None:
    await conn.execute(
        "INSERT INTO audit_log (ts, action, payload_json, result_json) "
        "VALUES ('2026-07-06T00:00:00+00:00', ?, '{}', '{}')",
        (action,),
    )


async def _audit_rows(conn: aiosqlite.Connection) -> list[tuple[int, str]]:
    cursor = await conn.execute("SELECT id, action FROM audit_log ORDER BY id")
    rows = await cursor.fetchall()
    await cursor.close()
    return [(int(r[0]), str(r[1])) for r in rows]


async def test_inserts_are_allowed_appending_is_the_point(
    tmp_db_path: Path, real_migrations_dir: Path
) -> None:
    conn = await _migrated_connection(tmp_db_path, real_migrations_dir)
    try:
        await _insert_audit_row(conn, "first")
        await _insert_audit_row(conn, "second")
        assert [action for _, action in await _audit_rows(conn)] == ["first", "second"]
    finally:
        await conn.close()


async def test_update_on_audit_log_aborts_and_leaves_the_row_intact(
    tmp_db_path: Path, real_migrations_dir: Path
) -> None:
    """History rewrite attempt: UPDATE must abort AND change nothing."""
    conn = await _migrated_connection(tmp_db_path, real_migrations_dir)
    try:
        await _insert_audit_row(conn, "original")
        with pytest.raises(sqlite3.DatabaseError, match="append-only"):
            await conn.execute("UPDATE audit_log SET action = 'tampered'")
        assert await _audit_rows(conn) == [(1, "original")]  # untouched, to the byte
    finally:
        await conn.close()


async def test_delete_on_audit_log_aborts_and_leaves_the_row_intact(
    tmp_db_path: Path, real_migrations_dir: Path
) -> None:
    """Evidence destruction attempt: DELETE must abort AND remove nothing."""
    conn = await _migrated_connection(tmp_db_path, real_migrations_dir)
    try:
        await _insert_audit_row(conn, "evidence")
        with pytest.raises(sqlite3.DatabaseError, match="append-only"):
            await conn.execute("DELETE FROM audit_log")
        assert await _audit_rows(conn) == [(1, "evidence")]
    finally:
        await conn.close()


async def test_targeted_single_row_update_and_delete_also_abort(
    tmp_db_path: Path, real_migrations_dir: Path
) -> None:
    """WHERE-clause precision does not evade the trigger (row-level firing)."""
    conn = await _migrated_connection(tmp_db_path, real_migrations_dir)
    try:
        await _insert_audit_row(conn, "keep-me")
        with pytest.raises(sqlite3.DatabaseError, match="append-only"):
            await conn.execute("UPDATE audit_log SET result_json = 'x' WHERE id = 1")
        with pytest.raises(sqlite3.DatabaseError, match="append-only"):
            await conn.execute("DELETE FROM audit_log WHERE id = 1")
        assert await _audit_rows(conn) == [(1, "keep-me")]
    finally:
        await conn.close()


async def test_failed_tamper_attempt_does_not_block_further_appends(
    tmp_db_path: Path, real_migrations_dir: Path
) -> None:
    """After an aborted UPDATE/DELETE the log must keep accepting appends —
    the abort is surgical, not a wedge."""
    conn = await _migrated_connection(tmp_db_path, real_migrations_dir)
    try:
        await _insert_audit_row(conn, "before-attack")
        with pytest.raises(sqlite3.DatabaseError):
            await conn.execute("DELETE FROM audit_log")
        await _insert_audit_row(conn, "after-attack")
        assert [a for _, a in await _audit_rows(conn)] == ["before-attack", "after-attack"]
    finally:
        await conn.close()


async def test_both_guard_triggers_exist_in_the_schema(
    tmp_db_path: Path, real_migrations_dir: Path
) -> None:
    """The invariant lives in the schema; assert the triggers are present so
    a future migration cannot silently drop them."""
    conn = await _migrated_connection(tmp_db_path, real_migrations_dir)
    try:
        cursor = await conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'trigger' AND tbl_name = 'audit_log'"
        )
        trigger_names = {str(row[0]) for row in await cursor.fetchall()}
        await cursor.close()
    finally:
        await conn.close()
    assert {"audit_log_block_update", "audit_log_block_delete"} <= trigger_names
