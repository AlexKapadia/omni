"""Shared fakes/fixtures for the M4 agents + google test files.

Synthetic only (claude.md §5.5): the fake Google session never opens a
socket; every test drives the real repositories against a tmp_path SQLite
database migrated with the REAL migration files.
"""

from pathlib import Path
from typing import Any

import aiosqlite

from engine.google.google_session import GoogleSession
from engine.storage import apply_migrations, open_sqlite_connection

TS = "2026-07-06T12:00:00+00:00"


class FakeGoogleSession(GoogleSession):
    """Records every request; replies from a canned queue (offline)."""

    def __init__(self, responses: list[dict[str, Any]] | None = None) -> None:
        self.requests: list[tuple[str, str, dict[str, object] | None]] = []
        self._responses = list(responses or [])

    async def request_json(
        self,
        method: str,
        url: str,
        *,
        params: dict[str, str] | None = None,
        json_body: dict[str, object] | None = None,
    ) -> dict[str, object]:
        self.requests.append((method, url, json_body))
        if not self._responses:
            raise AssertionError("FakeGoogleSession got an unexpected request")
        return self._responses.pop(0)


async def migrated_connection(
    tmp_db_path: Path, real_migrations_dir: Path
) -> aiosqlite.Connection:
    """A connection to a freshly migrated throwaway database."""
    await apply_migrations(tmp_db_path, real_migrations_dir)
    return await open_sqlite_connection(tmp_db_path)


async def insert_meeting(
    connection: aiosqlite.Connection,
    meeting_id: str = "m-1",
    *,
    note_path: str | None = None,
) -> str:
    await connection.execute(
        "INSERT INTO meetings (id, title, started_at, note_path)"
        " VALUES (?, 'Test meeting', ?, ?)",
        (meeting_id, TS, note_path),
    )
    return meeting_id


async def approved_card(
    connection: aiosqlite.Connection,
    *,
    card_type: str = "write_note",
    payload_json: str = '{"title": "T", "body_markdown": "B"}',
    meeting_id: str | None = None,
    source: str = "dictation",
    source_row_id: int = 1,
) -> int:
    """Insert a card and walk it to 'approved' through the legal path."""
    cursor = await connection.execute(
        "INSERT INTO approval_cards"
        " (meeting_id, source, source_row_id, card_type, payload_json, status, created_at)"
        " VALUES (?, ?, ?, ?, ?, 'pending', ?)",
        (meeting_id, source, source_row_id, card_type, payload_json, TS),
    )
    card_id = int(cursor.lastrowid or 0)
    await connection.execute(
        "UPDATE approval_cards SET status = 'approved', decided_at = ? WHERE id = ?",
        (TS, card_id),
    )
    return card_id


async def audit_rows(connection: aiosqlite.Connection) -> list[tuple[str, str, str]]:
    cursor = await connection.execute(
        "SELECT action, payload_json, COALESCE(result_json, '') FROM audit_log ORDER BY id"
    )
    rows = await cursor.fetchall()
    await cursor.close()
    return [(str(r[0]), str(r[1]), str(r[2])) for r in rows]


async def card_status(connection: aiosqlite.Connection, card_id: int) -> str:
    cursor = await connection.execute(
        "SELECT status FROM approval_cards WHERE id = ?", (card_id,)
    )
    row = await cursor.fetchone()
    await cursor.close()
    assert row is not None
    return str(row[0])
