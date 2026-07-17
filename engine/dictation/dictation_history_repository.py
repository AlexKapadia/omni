"""Append-only dictation history for in-app search and Ask scope."""

from __future__ import annotations

from collections.abc import Sequence

import aiosqlite

__all__ = [
    "insert_dictation_entry",
    "list_dictation_entries",
    "search_dictation_entries",
]


async def insert_dictation_entry(
    connection: aiosqlite.Connection,
    *,
    created_at_iso: str,
    mode: str,
    raw_text: str,
    cleaned_text: str | None = None,
    note_path: str | None = None,
    note_title: str | None = None,
    cleanup_style: str | None = None,
    stt_engine: str | None = None,
) -> int:
    cursor = await connection.execute(
        "INSERT INTO dictation_entries "
        "(created_at, mode, raw_text, cleaned_text, note_path, note_title, "
        "cleanup_style, stt_engine) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            created_at_iso,
            mode,
            raw_text,
            cleaned_text,
            note_path,
            note_title,
            cleanup_style,
            stt_engine,
        ),
    )
    row_id = cursor.lastrowid
    await cursor.close()
    if row_id is None:
        raise RuntimeError("dictation_entries insert did not return a row id")
    return int(row_id)


async def list_dictation_entries(
    connection: aiosqlite.Connection,
    *,
    limit: int = 100,
    offset: int = 0,
) -> list[dict[str, object]]:
    cursor = await connection.execute(
        "SELECT id, created_at, mode, raw_text, cleaned_text, note_path, "
        "note_title, cleanup_style, stt_engine "
        "FROM dictation_entries ORDER BY created_at DESC LIMIT ? OFFSET ?",
        (limit, offset),
    )
    rows = await cursor.fetchall()
    await cursor.close()
    return [_row_to_dict(row) for row in rows]


async def search_dictation_entries(
    connection: aiosqlite.Connection,
    query: str,
    *,
    limit: int = 50,
) -> list[dict[str, object]]:
    stripped = query.strip()
    if not stripped:
        return []
    pattern = f"%{stripped}%"
    cursor = await connection.execute(
        "SELECT id, created_at, mode, raw_text, cleaned_text, note_path, "
        "note_title, cleanup_style, stt_engine "
        "FROM dictation_entries "
        "WHERE raw_text LIKE ? OR cleaned_text LIKE ? OR note_title LIKE ? "
        "ORDER BY created_at DESC LIMIT ?",
        (pattern, pattern, pattern, limit),
    )
    rows = await cursor.fetchall()
    await cursor.close()
    return [_row_to_dict(row) for row in rows]


def _row_to_dict(row: Sequence[object]) -> dict[str, object]:
    return {
        "id": row[0],
        "created_at": row[1],
        "mode": row[2],
        "raw_text": row[3],
        "cleaned_text": row[4],
        "note_path": row[5],
        "note_title": row[6],
        "cleanup_style": row[7],
        "stt_engine": row[8],
    }
