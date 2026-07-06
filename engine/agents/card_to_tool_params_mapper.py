"""Deterministic card-payload -> tool-params mapping (LLM only as fallback).

Purpose: translate an APPROVED card's payload into concrete tool parameters
WITHOUT a model whenever possible. Deterministic mapping is preferred
because it is exact, free, auditable, and cannot be prompt-injected; the
executor falls back to router function-calling ONLY for the cases named
here as ambiguous (natural-language dates/times, non-address recipients),
where symbolic code genuinely cannot resolve the user's meaning.
Pipeline position: called by ``card_executor`` after payload validation.
"""

from dataclasses import dataclass

from pydantic import BaseModel, ValidationError

from engine.agents.approval_card_types import (
    CardPayload,
    CreateEventCardPayload,
    DraftEmailCardPayload,
    FindSlotCardPayload,
    UpsertContactCardPayload,
    WriteNoteCardPayload,
)
from engine.agents.calendar_create_event_tool import CalendarCreateEventParams
from engine.agents.calendar_find_free_slot_tool import CalendarFindFreeSlotParams
from engine.agents.contacts_upsert_tool import ContactsUpsertParams
from engine.agents.gmail_create_draft_tool import GmailCreateDraftParams
from engine.agents.vault_write_note_tool import VaultWriteNoteParams


@dataclass(frozen=True)
class MappingOutcome:
    """Either concrete params, or the honest reason mapping needs the LLM."""

    params: BaseModel | None
    ambiguity_reason: str | None

    @property
    def is_deterministic(self) -> bool:
        return self.params is not None


def _ambiguous(reason: str) -> MappingOutcome:
    return MappingOutcome(params=None, ambiguity_reason=reason)


def _mapped(params: BaseModel) -> MappingOutcome:
    return MappingOutcome(params=params, ambiguity_reason=None)


def map_card_payload_to_tool_params(payload: CardPayload) -> MappingOutcome:
    """Try the exact, model-free translation for one validated payload."""
    if isinstance(payload, CreateEventCardPayload):
        return _map_create_event(payload)
    if isinstance(payload, FindSlotCardPayload):
        return _map_find_slot(payload)
    if isinstance(payload, UpsertContactCardPayload):
        # Contacts map 1:1 — there is never anything to "resolve".
        return _mapped(
            ContactsUpsertParams(
                name=payload.name,
                phone=payload.phone,
                email=payload.email,
                company=payload.company,
                sync_to_google=payload.sync_to_google,
            )
        )
    if isinstance(payload, WriteNoteCardPayload):
        return _mapped(
            VaultWriteNoteParams(title=payload.title, body_markdown=payload.body_markdown)
        )
    # Exhaustive over CardPayload: the remaining member is draft_email.
    return _map_draft_email(payload)


def _map_create_event(payload: CreateEventCardPayload) -> MappingOutcome:
    """Deterministic only with explicit ISO start AND end.

    "Friday at 1" cannot be resolved symbolically without inventing a
    convention the user never stated — that is exactly the LLM fallback's
    job (with the reference clock in its frame).
    """
    if not payload.start_iso or not payload.end_iso:
        return _ambiguous(
            "event time is natural language, not explicit ISO start/end — "
            f"needs resolution (hint: {payload.when_hint or 'none'})"
        )
    try:
        params = CalendarCreateEventParams(
            title=payload.title,
            start_iso=payload.start_iso,
            end_iso=payload.end_iso,
            description=payload.description or "",
            # Only real addresses can be invited deterministically; bare
            # names would need resolution we refuse to guess at.
            attendee_emails=[a for a in payload.attendees if "@" in a],
        )
    except ValidationError as error:
        return _ambiguous(f"explicit event fields did not validate: {error}")
    return _mapped(params)


def _map_find_slot(payload: FindSlotCardPayload) -> MappingOutcome:
    if not payload.window_start_iso or not payload.window_end_iso:
        return _ambiguous("search window is not an explicit ISO start/end pair")
    try:
        params = CalendarFindFreeSlotParams(
            duration_minutes=payload.duration_minutes,
            window_start_iso=payload.window_start_iso,
            window_end_iso=payload.window_end_iso,
            description=payload.description or "",
        )
    except ValidationError as error:
        return _ambiguous(f"explicit window fields did not validate: {error}")
    return _mapped(params)


def _map_draft_email(payload: DraftEmailCardPayload) -> MappingOutcome:
    non_addresses = [a for a in payload.to if "@" not in a]
    if non_addresses:
        # fail-closed: we never guess an email address for a bare name — and
        # neither may the LLM invent one; validation will refuse it again.
        return _ambiguous(
            f"recipients are names, not addresses: {', '.join(non_addresses)}"
        )
    try:
        params = GmailCreateDraftParams(
            to=list(payload.to),
            subject=payload.subject or "(no subject)",
            body_text=payload.body_hint or "",
        )
    except ValidationError as error:
        return _ambiguous(f"draft fields did not validate: {error}")
    return _mapped(params)
