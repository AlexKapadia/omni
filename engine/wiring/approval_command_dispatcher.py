"""``cards.list`` / ``card.approve`` / ``card.dismiss`` / ``card.retry`` dispatch.

Purpose: the ADDITIVE M4 approval-card command surface, implemented EXACTLY
per the pinned spec in ``engine/agents/approval_protocol_names.py`` —
validates untrusted payloads, drives :class:`ApprovalCardsGateway`, and
answers with the house reply shapes (``ok`` / ``error``), keeping the diff
inside ``engine.websocket_connection_handler`` to a single delegation
branch (same pattern as the meeting/ask/dictation dispatchers).
Pipeline position: called by the connection handler for any command whose
name is in ``APPROVAL_COMMAND_NAMES``; speaks only ``engine.protocol``
envelopes.

Security invariants:
- Strict payload validation (extra fields forbidden) — deny by default; a
  malformed frame never reaches the gateway.
- Refusals (unknown id, illegal transition, invalid pre-approval edit, and
  any SQL-trigger abort from the 0008 status machine) become structured
  ``card_error`` replies; the socket never crashes and no refusal is
  silent (fail closed, visibly).
"""

import logging
from collections.abc import Awaitable, Callable

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from engine.agents.approval_protocol_names import (
    CARD_APPROVE_COMMAND_NAME,
    CARD_DISMISS_COMMAND_NAME,
    CARD_RETRY_COMMAND_NAME,
    CARDS_LIST_COMMAND_NAME,
)
from engine.protocol import (
    PROTOCOL_VERSION,
    Envelope,
    EnvelopeKind,
    ProtocolErrorCode,
    error_reply,
)
from engine.wiring.approval_cards_gateway import ApprovalCardsGateway, CardCommandRefused

logger = logging.getLogger(__name__)

# The commands this dispatcher owns; the handler routes ONLY these here.
APPROVAL_COMMAND_NAMES = frozenset(
    {
        CARDS_LIST_COMMAND_NAME,
        CARD_APPROVE_COMMAND_NAME,
        CARD_DISMISS_COMMAND_NAME,
        CARD_RETRY_COMMAND_NAME,
    }
)

# Additive error code (string literal beside the pinned enum, mirroring the
# meeting dispatcher's `finalize_error`).
CARD_ERROR_CODE = "card_error"

SendFn = Callable[[Envelope], Awaitable[None]]


class CardsListCommandPayload(BaseModel):
    """Payload of ``cards.list`` — deliberately empty (deny extras)."""

    model_config = ConfigDict(extra="forbid")


class CardApproveCommandPayload(BaseModel):
    """Payload of ``card.approve``: {id, edited_payload?} (pinned spec)."""

    # strict: a stringly "1" (or a bool) is not a card id — deny by default.
    model_config = ConfigDict(extra="forbid", strict=True)
    id: int = Field(ge=1)
    # The user's pre-approval edit; validated against the card's typed
    # payload model in the gateway before the approve statement.
    edited_payload: dict[str, object] | None = None


class CardDismissCommandPayload(BaseModel):
    """Payload of ``card.dismiss``: {id}."""

    # strict: a stringly "1" (or a bool) is not a card id — deny by default.
    model_config = ConfigDict(extra="forbid", strict=True)
    id: int = Field(ge=1)


class CardRetryCommandPayload(BaseModel):
    """Payload of ``card.retry``: {id} (must name a FAILED card)."""

    # strict: a stringly "1" (or a bool) is not a card id — deny by default.
    model_config = ConfigDict(extra="forbid", strict=True)
    id: int = Field(ge=1)


def _ok_reply(reply_id: str, payload: dict[str, object]) -> Envelope:
    return Envelope(
        v=PROTOCOL_VERSION, kind=EnvelopeKind.REPLY, name="ok", id=reply_id, payload=dict(payload)
    )


def _card_error_reply(reply_id: str, message: str) -> Envelope:
    return Envelope(
        v=PROTOCOL_VERSION,
        kind=EnvelopeKind.REPLY,
        name="error",
        id=reply_id,
        payload={"code": CARD_ERROR_CODE, "message": message},
    )


async def dispatch_approval_command(
    command: Envelope, gateway: ApprovalCardsGateway | None, send: SendFn
) -> None:
    """Handle one validated cards/card.* command envelope, always replying."""
    if gateway is None:
        # Approval cards not wired in this app instance: refuse honestly.
        await send(_card_error_reply(command.id, "approval cards are not available"))
        return
    try:
        if command.name == CARDS_LIST_COMMAND_NAME:
            CardsListCommandPayload.model_validate(command.payload)
            await send(_ok_reply(command.id, await gateway.list_cards_payload()))
            return
        if command.name == CARD_APPROVE_COMMAND_NAME:
            approve = CardApproveCommandPayload.model_validate(command.payload)
            await gateway.approve(approve.id, approve.edited_payload)
        elif command.name == CARD_DISMISS_COMMAND_NAME:
            dismiss = CardDismissCommandPayload.model_validate(command.payload)
            await gateway.dismiss(dismiss.id)
        else:  # CARD_RETRY_COMMAND_NAME — the handler routes only these four
            retry = CardRetryCommandPayload.model_validate(command.payload)
            await gateway.retry(retry.id)
    except ValidationError:
        await send(
            error_reply(
                command.id,
                ProtocolErrorCode.INVALID_PAYLOAD,
                f"{command.name} payload failed validation",
            )
        )
        return
    except CardCommandRefused as exc:
        # Honest refusal (unknown id / illegal transition / invalid edit).
        await send(_card_error_reply(command.id, str(exc)))
        return
    except Exception as exc:
        # Includes 0008 trigger aborts surfacing as sqlite errors: the SQL
        # layer refused an illegal transition — report it, never crash.
        logger.exception("%s failed", command.name)
        await send(_card_error_reply(command.id, f"{command.name} failed: {exc}"))
        return
    # Decisions acknowledge with an empty ok; state travels exclusively via
    # the card.updated events (the UI is optimistic-free by contract).
    await send(_ok_reply(command.id, {}))
