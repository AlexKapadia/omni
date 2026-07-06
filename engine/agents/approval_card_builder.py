"""Builds approval cards from extraction results (the extraction half).

Purpose: turn append-only ``extraction_results`` (0005) payloads into
typed, PENDING approval cards, and host the collector/insert plumbing the
dictation half (``dictation_intent_card_builder``) shares. This module
only SUGGESTS; nothing here executes anything (approval-before-execute
lives in the 0008 schema + executor).
Pipeline position: called after meeting finalization; the cards feed the
UI rack.

Robustness invariants:
- Source rows are UNTRUSTED model output: a malformed row — bad JSON,
  wrong shapes, over-long fields — is SKIPPED with a log line, never a
  crash and never a half-built card (fail closed per item).
- Idempotent: re-running over the same source rows creates no duplicate
  cards (exact source+type+payload match is skipped).
- Confidence floor: dictation intents below the floor are not auto-
  suggested — a barely-parsed command must not become a one-click action.
"""

import json
import logging
from dataclasses import dataclass, field

import aiosqlite
from pydantic import BaseModel, ValidationError

from engine.agents.approval_card_types import (
    CardType,
    CreateEventCardPayload,
    UpsertContactCardPayload,
)
from engine.agents.approval_cards_repository import identical_card_exists, insert_pending_card

_logger = logging.getLogger(__name__)

# Deny-by-default floor: below this, a dictation parse is recorded (0007)
# but never surfaced as an actionable card.
DICTATION_CONFIDENCE_FLOOR = 0.6

SOURCE_EXTRACTION = "extraction"
SOURCE_DICTATION = "dictation"



@dataclass(frozen=True)
class BuiltCards:
    """What one build pass produced — created ids plus honest skip reasons."""

    created_card_ids: tuple[int, ...] = ()
    skipped: tuple[str, ...] = ()


@dataclass
class _BuildCollector:
    created: list[int] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)

    def skip(self, reason: str) -> None:
        _logger.warning("approval-card builder skipped a candidate: %s", reason)
        self.skipped.append(reason)

    def result(self) -> BuiltCards:
        return BuiltCards(created_card_ids=tuple(self.created), skipped=tuple(self.skipped))


def _clean_str(value: object, *, max_length: int = 200) -> str | None:
    """A trimmed non-empty string, or None — no coercion of other types."""
    if not isinstance(value, str):
        return None
    trimmed = value.strip()
    return trimmed[:max_length] if trimmed else None


async def _insert_unless_duplicate(
    connection: aiosqlite.Connection,
    collector: _BuildCollector,
    *,
    meeting_id: str | None,
    source: str,
    source_row_id: int,
    card_type: CardType,
    payload: BaseModel,
    created_at: str,
) -> None:
    payload_json = payload.model_dump_json()
    if await identical_card_exists(
        connection,
        source=source,
        source_row_id=source_row_id,
        card_type=card_type.value,
        payload_json=payload_json,
    ):
        collector.skip(
            f"{source} row {source_row_id}: identical {card_type.value} card already exists"
        )
        return
    card_id = await insert_pending_card(
        connection,
        meeting_id=meeting_id,
        source=source,
        source_row_id=source_row_id,
        card_type=card_type.value,
        payload_json=payload_json,
        created_at=created_at,
    )
    collector.created.append(card_id)


async def build_cards_from_extraction(
    connection: aiosqlite.Connection,
    *,
    meeting_id: str,
    extraction_row_id: int,
    payload_json: str,
    created_at: str,
) -> BuiltCards:
    """Cards from one extraction pass: contacts -> upsert_contact,
    dates -> create_event (time left as a hint for the executor to
    resolve). Actions/commitments already land in the note's Actions
    region — duplicating them as cards would be noise, not help."""
    collector = _BuildCollector()
    try:
        decoded = json.loads(payload_json)
    except (json.JSONDecodeError, RecursionError) as error:
        collector.skip(f"extraction row {extraction_row_id}: payload is not JSON ({error})")
        return collector.result()
    if not isinstance(decoded, dict):
        collector.skip(f"extraction row {extraction_row_id}: payload is not an object")
        return collector.result()

    contacts = decoded.get("contacts", [])
    for item in contacts if isinstance(contacts, list) else ():
        if not isinstance(item, dict):
            collector.skip(f"extraction row {extraction_row_id}: contact item is not an object")
            continue
        name = _clean_str(item.get("name"))
        if name is None:
            collector.skip(f"extraction row {extraction_row_id}: contact has no usable name")
            continue
        try:
            payload = UpsertContactCardPayload(
                name=name,
                phone=_clean_str(item.get("phone")),
                email=_clean_str(item.get("email")),
                company=_clean_str(item.get("company")),
            )
        except ValidationError as error:
            collector.skip(f"extraction row {extraction_row_id}: contact invalid ({error})")
            continue
        await _insert_unless_duplicate(
            connection,
            collector,
            meeting_id=meeting_id,
            source=SOURCE_EXTRACTION,
            source_row_id=extraction_row_id,
            card_type=CardType.UPSERT_CONTACT,
            payload=payload,
            created_at=created_at,
        )

    dates = decoded.get("dates", [])
    for item in dates if isinstance(dates, list) else ():
        if not isinstance(item, dict):
            collector.skip(f"extraction row {extraction_row_id}: date item is not an object")
            continue
        what = _clean_str(item.get("what"), max_length=500)
        when = _clean_str(item.get("when"))
        if what is None or when is None:
            collector.skip(f"extraction row {extraction_row_id}: date item missing when/what")
            continue
        try:
            payload_event = CreateEventCardPayload(title=what, when_hint=when)
        except ValidationError as error:
            collector.skip(f"extraction row {extraction_row_id}: date invalid ({error})")
            continue
        await _insert_unless_duplicate(
            connection,
            collector,
            meeting_id=meeting_id,
            source=SOURCE_EXTRACTION,
            source_row_id=extraction_row_id,
            card_type=CardType.CREATE_EVENT,
            payload=payload_event,
            created_at=created_at,
        )
    return collector.result()
