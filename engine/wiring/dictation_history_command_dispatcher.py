"""``dictation.history.list`` command dispatch."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from pathlib import Path

from engine.dictation.dictation_history_repository import list_dictation_entries, search_dictation_entries
from engine.dictation.dictation_protocol_names import (
    DICTATION_HISTORY_LIST_COMMAND_NAME,
    build_dictation_history_list_payload,
)
from engine.protocol import PROTOCOL_VERSION, Envelope, EnvelopeKind
from engine.storage.sqlite_connection import open_sqlite_connection
from engine.storage.sqlite_migrations_runner import apply_migrations

SendFn = Callable[[Envelope], Awaitable[None]]

DICTATION_HISTORY_COMMAND_NAMES = frozenset({DICTATION_HISTORY_LIST_COMMAND_NAME})


async def dispatch_dictation_history_command(
    command: Envelope,
    *,
    db_path: Path,
    migrations_dir: Path,
    send: SendFn,
) -> None:
    if command.name != DICTATION_HISTORY_LIST_COMMAND_NAME:
        await send(_error_reply(command.id, "unknown dictation history command"))
        return
    query = command.payload.get("query")
    limit = command.payload.get("limit", 100)
    if not isinstance(limit, int) or limit < 1 or limit > 500:
        limit = 100
    await apply_migrations(db_path, migrations_dir)
    connection = await open_sqlite_connection(db_path)
    try:
        if isinstance(query, str) and query.strip():
            entries = await search_dictation_entries(connection, query, limit=limit)
        else:
            entries = await list_dictation_entries(connection, limit=limit)
    finally:
        await connection.close()
    await send(
        Envelope(
            v=PROTOCOL_VERSION,
            kind=EnvelopeKind.REPLY,
            name="ok",
            id=command.id,
            payload=build_dictation_history_list_payload(entries),
        )
    )


def _error_reply(reply_id: str, message: str) -> Envelope:
    return Envelope(
        v=PROTOCOL_VERSION,
        kind=EnvelopeKind.REPLY,
        name="error",
        id=reply_id,
        payload={"code": "dictation_error", "message": message},
    )
