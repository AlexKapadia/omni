"""Repository for ``extraction_results`` rows (append-only extraction output).

Purpose: the only place extraction results are written or read — one row
per extraction pass over a finalised meeting, appended by the M2
finalization service and read later by M4's approval cards. Re-running
extraction appends a newer row; nothing is ever updated (the schema's
RAISE(ABORT) triggers enforce append-only, mirroring the audit log).
Pipeline position: called by ``engine.enhance.meeting_finalization_service``
after the extraction pipeline validates its JSON.

Security invariants:
- Parameterised SQL only — payload JSON derives from untrusted transcript
  content and must never be interpolated (injection defence).
- Append-only is enforced IN THE SCHEMA (migrations/0005), not by code
  convention; this repository only ever INSERTs and SELECTs.
"""

import aiosqlite


async def insert_extraction_result(
    connection: aiosqlite.Connection, meeting_id: str, ts_iso: str, payload_json: str
) -> None:
    """Append one validated extraction payload for a meeting."""
    await connection.execute(
        "INSERT INTO extraction_results (meeting_id, ts, payload_json) VALUES (?, ?, ?)",
        (meeting_id, ts_iso, payload_json),
    )


async def latest_extraction_payload_json(
    connection: aiosqlite.Connection, meeting_id: str
) -> str | None:
    """The newest extraction payload for a meeting, or None when absent.

    Newest by (ts, id): id breaks exact-timestamp ties because it is the
    monotonic append order — the later row is always the later pass.
    """
    cursor = await connection.execute(
        "SELECT payload_json FROM extraction_results"
        " WHERE meeting_id = ? ORDER BY ts DESC, id DESC LIMIT 1",
        (meeting_id,),
    )
    row = await cursor.fetchone()
    await cursor.close()
    return None if row is None else str(row[0])
