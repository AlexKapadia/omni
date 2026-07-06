"""Builds at most one approval card from one recorded dictation intent.

Purpose: the dictation half of card building — map a ``dictation_intents``
(0007) row onto a typed PENDING card, deterministically and fail-soft.
Nothing here executes anything; M5 records, M4 suggests, only the executor
acts on schema-approved cards (approval-before-execute).
Pipeline position: called after a dictation command release lands its
intent row; shares the collector/insert plumbing with
``approval_card_builder`` (the extraction half).

Robustness invariants (mirroring the extraction builder):
- Intent fields are UNTRUSTED model output: malformed fields are skipped
  with a log line, never a crash, never a half-built card.
- Confidence floor (deny by default): a barely-parsed command is recorded
  but never surfaced as a one-click action.
- 'unknown' intents never become cards.
"""

import json

import aiosqlite
from pydantic import BaseModel, ValidationError

from engine.agents.approval_card_builder import (
    DICTATION_CONFIDENCE_FLOOR,
    SOURCE_DICTATION,
    BuiltCards,
    _BuildCollector,
    _clean_str,
    _insert_unless_duplicate,
)
from engine.agents.approval_card_types import (
    CardType,
    CreateEventCardPayload,
    DraftEmailCardPayload,
    UpsertContactCardPayload,
    WriteNoteCardPayload,
)
from engine.dictation.dictation_intents_repository import DictationIntentRecord

_INTENT_TYPE_TO_CARD_TYPE: dict[str, CardType] = {
    "create_event": CardType.CREATE_EVENT,
    "upsert_contact": CardType.UPSERT_CONTACT,
    "draft_email": CardType.DRAFT_EMAIL,
    "write_note": CardType.WRITE_NOTE,
    # "unknown" deliberately absent: unparseable commands never become cards.
}


async def build_card_from_dictation_intent(
    connection: aiosqlite.Connection,
    *,
    record: DictationIntentRecord,
    created_at: str,
) -> BuiltCards:
    """At most one card from one recorded dictation intent."""
    collector = _BuildCollector()
    card_type = _INTENT_TYPE_TO_CARD_TYPE.get(record.intent_type)
    if card_type is None:
        collector.skip(f"dictation intent {record.id}: type '{record.intent_type}' has no card")
        return collector.result()
    if record.confidence < DICTATION_CONFIDENCE_FLOOR:
        collector.skip(
            f"dictation intent {record.id}: confidence {record.confidence} is below "
            f"the {DICTATION_CONFIDENCE_FLOOR} floor — not auto-suggested"
        )
        return collector.result()
    try:
        fields_decoded = json.loads(record.fields_json)
    except (json.JSONDecodeError, RecursionError) as error:
        collector.skip(f"dictation intent {record.id}: fields are not JSON ({error})")
        return collector.result()
    if not isinstance(fields_decoded, dict):
        collector.skip(f"dictation intent {record.id}: fields are not an object")
        return collector.result()
    try:
        payload = _dictation_payload(card_type, fields_decoded, record)
    except ValidationError as error:
        collector.skip(f"dictation intent {record.id}: fields invalid ({error})")
        return collector.result()
    if payload is None:
        collector.skip(f"dictation intent {record.id}: no usable fields for {card_type.value}")
        return collector.result()
    await _insert_unless_duplicate(
        connection,
        collector,
        meeting_id=None,  # dictation is not meeting-bound
        source=SOURCE_DICTATION,
        source_row_id=record.id,
        card_type=card_type,
        payload=payload,
        created_at=created_at,
    )
    return collector.result()


def _dictation_payload(
    card_type: CardType, fields: dict[str, object], record: DictationIntentRecord
) -> BaseModel | None:
    """Deterministic field normalisation per intent type (no invention:
    only what the parser extracted or the verbatim raw_text is used)."""
    if card_type is CardType.CREATE_EVENT:
        title = (
            _clean_str(fields.get("title"), max_length=500)
            or _clean_str(fields.get("event"), max_length=500)
            or _clean_str(fields.get("what"), max_length=500)
            or _clean_str(record.raw_text, max_length=500)
        )
        when_parts = [
            part
            for key in ("when", "date", "time", "datetime")
            if (part := _clean_str(fields.get(key))) is not None
        ]
        if title is None:
            return None
        return CreateEventCardPayload(
            title=title, when_hint=" ".join(when_parts) if when_parts else None
        )
    if card_type is CardType.UPSERT_CONTACT:
        name = _clean_str(fields.get("name")) or _clean_str(fields.get("person"))
        if name is None:
            return None  # a contact card without a name is unactionable
        return UpsertContactCardPayload(
            name=name,
            phone=_clean_str(fields.get("phone")),
            email=_clean_str(fields.get("email")),
            company=_clean_str(fields.get("company")),
        )
    if card_type is CardType.DRAFT_EMAIL:
        recipient = (
            _clean_str(fields.get("to"))
            or _clean_str(fields.get("recipient"))
            or _clean_str(fields.get("person"))
        )
        body = _clean_str(fields.get("body"), max_length=20_000) or _clean_str(
            fields.get("message"), max_length=20_000
        )
        return DraftEmailCardPayload(
            to=[recipient] if recipient is not None else [],
            subject=_clean_str(fields.get("subject"), max_length=500),
            body_hint=body,
        )
    if card_type is CardType.WRITE_NOTE:
        title = _clean_str(fields.get("title")) or _clean_str(fields.get("topic"))
        body = (
            _clean_str(fields.get("body"), max_length=20_000)
            or _clean_str(fields.get("content"), max_length=20_000)
            or _clean_str(fields.get("note"), max_length=20_000)
            or _clean_str(record.raw_text, max_length=20_000)
        )
        if body is None:
            return None
        return WriteNoteCardPayload(
            title=title or f"Dictated note {record.ts[:10]}", body_markdown=body
        )
    return None
