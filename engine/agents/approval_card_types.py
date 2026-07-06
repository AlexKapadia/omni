"""Typed approval-card shapes: card types, statuses, and payload models.

Purpose: the ONE definition of what each approval card carries. Card payloads
are built from UNTRUSTED source rows (model-extracted meeting content and
dictation transcripts), so every field is bounded and every model rejects
unknown keys — a payload either validates exactly or the card is refused.
Pipeline position: written by ``approval_card_builder``, stored as
``approval_cards.payload_json`` (migrations/0008), parsed back by
``card_executor`` before any tool runs.

Security invariants:
- Enum values are pinned by the 0008 CHECK constraints — do not rename.
- ``extra="forbid"`` everywhere: extracted content cannot smuggle fields the
  executor would then have to trust (injection defence, deny by default).
"""

import json
from dataclasses import dataclass
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from engine.agents.agents_errors import CardPayloadInvalidError

_SHORT = 200  # bound for names/hints (mirrors the extraction pipeline bounds)
_LONG = 500  # bound for titles/subjects
_BODY = 20_000  # bound for note/email bodies


class CardType(StrEnum):
    """Every action a card can propose (0008 ``card_type`` CHECK values)."""

    CREATE_EVENT = "create_event"
    FIND_SLOT = "find_slot"
    UPSERT_CONTACT = "upsert_contact"
    WRITE_NOTE = "write_note"
    DRAFT_EMAIL = "draft_email"


class CardStatus(StrEnum):
    """The 0008 status machine's states (transitions live in the SCHEMA)."""

    PENDING = "pending"
    APPROVED = "approved"
    EXECUTING = "executing"
    EXECUTED = "executed"
    FAILED = "failed"
    DISMISSED = "dismissed"


class CreateEventCardPayload(BaseModel):
    """A proposed calendar event. ``when_hint`` keeps the raw natural-language
    time so the executor's LLM fallback can resolve it when no explicit ISO
    datetimes were extracted (deterministic mapping first — see executor)."""

    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=1, max_length=_LONG)
    when_hint: str | None = Field(default=None, max_length=_SHORT)
    start_iso: str | None = Field(default=None, max_length=_SHORT)
    end_iso: str | None = Field(default=None, max_length=_SHORT)
    attendees: list[str] = Field(default_factory=list, max_length=20)
    description: str | None = Field(default=None, max_length=_BODY)


class FindSlotCardPayload(BaseModel):
    """A proposed free-slot search (read-only against the calendar)."""

    model_config = ConfigDict(extra="forbid")
    duration_minutes: int = Field(ge=1, le=24 * 60)
    window_start_iso: str | None = Field(default=None, max_length=_SHORT)
    window_end_iso: str | None = Field(default=None, max_length=_SHORT)
    description: str | None = Field(default=None, max_length=_LONG)


class UpsertContactCardPayload(BaseModel):
    """A proposed People-note upsert; Google sync is OPT-IN per card."""

    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=_SHORT)
    phone: str | None = Field(default=None, max_length=_SHORT)
    email: str | None = Field(default=None, max_length=_SHORT)
    company: str | None = Field(default=None, max_length=_SHORT)
    # Deny by default: the vault write is local; pushing the contact to
    # Google happens only when this is explicitly true on the approved card.
    sync_to_google: bool = False


class WriteNoteCardPayload(BaseModel):
    """A proposed new vault note (engine.vault only — no egress at all)."""

    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=1, max_length=_SHORT)
    body_markdown: str = Field(min_length=1, max_length=_BODY)


class DraftEmailCardPayload(BaseModel):
    """A proposed Gmail DRAFT. There is no send field anywhere in this model,
    the tools, or the gateway — drafts are the entire capability (binding)."""

    model_config = ConfigDict(extra="forbid")
    to: list[str] = Field(default_factory=list, max_length=10)
    subject: str | None = Field(default=None, max_length=_LONG)
    body_hint: str | None = Field(default=None, max_length=_BODY)


CardPayload = (
    CreateEventCardPayload
    | FindSlotCardPayload
    | UpsertContactCardPayload
    | WriteNoteCardPayload
    | DraftEmailCardPayload
)

PAYLOAD_MODEL_BY_CARD_TYPE: dict[CardType, type[BaseModel]] = {
    CardType.CREATE_EVENT: CreateEventCardPayload,
    CardType.FIND_SLOT: FindSlotCardPayload,
    CardType.UPSERT_CONTACT: UpsertContactCardPayload,
    CardType.WRITE_NOTE: WriteNoteCardPayload,
    CardType.DRAFT_EMAIL: DraftEmailCardPayload,
}


@dataclass(frozen=True)
class ApprovalCardRecord:
    """One ``approval_cards`` row, exactly as stored (the read shape)."""

    id: int
    meeting_id: str | None
    source: str
    source_row_id: int
    card_type: str
    payload_json: str
    status: str
    created_at: str
    decided_at: str | None
    executed_at: str | None
    result_json: str | None
    error: str | None


def parse_card_payload(card_type: str, payload_json: str) -> CardPayload:
    """Validate a stored payload against its pinned model, fail closed.

    Raises :class:`CardPayloadInvalidError` on unknown type, bad JSON, or any
    schema deviation — an unvalidated payload never reaches a tool.
    """
    try:
        model = PAYLOAD_MODEL_BY_CARD_TYPE[CardType(card_type)]
    except ValueError:
        raise CardPayloadInvalidError(card_type, "unknown card type") from None
    try:
        decoded = json.loads(payload_json)
    except (json.JSONDecodeError, RecursionError) as error:
        raise CardPayloadInvalidError(card_type, f"payload is not valid JSON: {error}") from None
    if not isinstance(decoded, dict):
        raise CardPayloadInvalidError(card_type, "payload JSON is not an object")
    try:
        validated = model.model_validate(decoded)
    except ValidationError as error:
        raise CardPayloadInvalidError(card_type, str(error)) from None
    # mypy: every registered model is a CardPayload member by construction.
    return validated  # type: ignore[return-value]
