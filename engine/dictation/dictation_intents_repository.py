"""Append-only repository over the ``dictation_intents`` table (0007).

Purpose: the single write/read path for recorded dictation command
intents. M5 writes one row per "Omni,"-prefixed release; M4's approval
cards read the rows to build cards. Parameterised SQL only — raw_text and
fields come from untrusted STT/model output.
Pipeline position: called by ``dictation_finalization`` after intent
parsing; migration 0007's schema triggers make UPDATE/DELETE impossible.

Security invariants:
- Append-only: no update/delete functions exist here, and the schema
  blocks them anyway (defence in depth).
- NEVER-execute: this module records intents; execution lives behind M4
  approval cards only (approval-before-execute invariant).
"""

from dataclasses import dataclass

import aiosqlite

from engine.dictation.dictation_intent_schema import ParsedIntent


@dataclass(frozen=True)
class DictationIntentRecord:
    """One persisted intent row, exactly as stored (read path for M4)."""

    id: int
    ts: str
    raw_text: str
    intent_type: str
    fields_json: str
    confidence: float
    provider: str | None
    model: str | None


async def insert_dictation_intent(
    connection: aiosqlite.Connection,
    *,
    ts: str,
    raw_text: str,
    intent: ParsedIntent,
    provider: str | None,
    model: str | None,
) -> int:
    """Append one intent row; returns its rowid.

    ``raw_text`` is the VERBATIM dictated text including the wake word
    (fidelity mandate: the ground truth is stored, not a cleaned copy).
    ``provider``/``model`` are ``None`` when the router was unavailable
    and the intent was recorded locally as ``unknown``.
    """
    cursor = await connection.execute(
        # Parameterised only — every value is untrusted input.
        "INSERT INTO dictation_intents"
        " (ts, raw_text, intent_type, fields_json, confidence, provider, model)"
        " VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            ts,
            raw_text,
            intent.intent_type.value,
            intent.fields_as_json(),
            intent.confidence,
            provider,
            model,
        ),
    )
    await connection.commit()
    row_id = cursor.lastrowid
    await cursor.close()
    # lastrowid is always set after a successful INSERT on this connection.
    return int(row_id if row_id is not None else 0)


async def list_dictation_intents(
    connection: aiosqlite.Connection, *, limit: int = 100
) -> list[DictationIntentRecord]:
    """Newest-first intents (M4 approval-card read path)."""
    cursor = await connection.execute(
        "SELECT id, ts, raw_text, intent_type, fields_json, confidence, provider, model"
        " FROM dictation_intents ORDER BY id DESC LIMIT ?",
        (limit,),
    )
    rows = await cursor.fetchall()
    await cursor.close()
    return [
        DictationIntentRecord(
            id=int(row[0]),
            ts=str(row[1]),
            raw_text=str(row[2]),
            intent_type=str(row[3]),
            fields_json=str(row[4]),
            confidence=float(row[5]),
            provider=None if row[6] is None else str(row[6]),
            model=None if row[7] is None else str(row[7]),
        )
        for row in rows
    ]
