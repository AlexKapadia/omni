"""Opens configured aiosqlite connections to the engine database.

Purpose: the single place connection pragmas are set, so every consumer
gets the same enforcement (foreign keys ON) instead of re-deciding per
call site.
Pipeline position: used by the migrations runner and, later, every
feature module's repository code.

Security invariant: ``foreign_keys = ON`` is enforced on every connection —
SQLite defaults it OFF per-connection, and referential integrity between
meetings and transcript segments must hold, not be optional.
"""

from pathlib import Path

import aiosqlite


async def open_sqlite_connection(db_path: Path) -> aiosqlite.Connection:
    """Open the engine database, creating parent directories if needed.

    The connection is returned in autocommit mode (``isolation_level=None``)
    so transaction boundaries are always explicit SQL (BEGIN/COMMIT) — the
    migrations runner depends on this for its atomicity guarantee.

    Callers own the connection and must close it (or use it as a context
    manager).
    """
    # First-run bootstrap: %LOCALAPPDATA%/Omni may not exist yet.
    db_path.parent.mkdir(parents=True, exist_ok=True)
    connection = await aiosqlite.connect(db_path, isolation_level=None)
    # Referential-integrity invariant: never rely on SQLite's OFF default.
    await connection.execute("PRAGMA foreign_keys = ON")
    return connection
