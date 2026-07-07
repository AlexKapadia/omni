"""Naomi's action path: utterance → intent → PENDING approval card (never runs).

Purpose: when the user tells Naomi to DO something ("schedule a review with
Priya on Friday", "draft an email to Sanjay"), Naomi prepares an approval
card and SAYS she prepared it — she never executes. Execution stays behind
the M4 approval surface (schema-approved cards only). This module reuses the
dictation intent parser and the dictation card builder, so Naomi's actions
travel the exact same audited, approval-gated rails as dictation commands.
Pipeline position: consulted by ``engine.naomi.naomi_turn_orchestrator`` on
each verbatim utterance BEFORE the answer service; a prepared action short-
circuits the answer (Naomi confirms the card instead of answering a question).

Security invariants (§5.6 approval-before-execute, deny by default):
- NEVER-execute: this flow only ever INSERTs a PENDING card (via the
  dictation card builder) and records the intent append-only. The card
  executor is unreachable from here — a pending card cannot be claimed for
  execution without first being approved (SQL-enforced elsewhere).
- Untrusted input: the utterance rides the router DATA channel; only the
  pinned INTENT_PARSING frame is instruction. Any parse deviation degrades
  to 'unknown' and NO card is built (fail closed).
- Confidence floor: a barely-parsed command is recorded but never surfaced
  as an action — below the floor, Naomi falls through to answering instead.
"""

from collections.abc import Callable
from dataclasses import dataclass

import aiosqlite

from engine.agents.approval_card_builder import DICTATION_CONFIDENCE_FLOOR
from engine.agents.dictation_intent_card_builder import build_card_from_dictation_intent
from engine.ask.ask_service_protocols import CompletionRouterProtocol
from engine.dictation.dictation_intent_schema import (
    DICTATION_INTENT_JSON_SCHEMA,
    INTENT_PARSING_SYSTEM_FRAME,
    DictationIntentType,
    parse_intent_completion_text,
)
from engine.dictation.dictation_intents_repository import (
    get_dictation_intent,
    insert_dictation_intent,
)
from engine.naomi.naomi_turn_latency_breakdown import milliseconds_between
from engine.router.completion_contract import ChatMessage

INTENT_PARSING_TASK = "intent_parsing"
# Cap the intent completion: a classification is small; a large reply is a
# misbehaving provider, not a longer intent (resource-exhaustion defence).
_INTENT_MAX_TOKENS = 500

# Conservative deterministic pre-filter: only utterances that OPEN with an
# imperative action verb are sent to the intent parser. Everything else is a
# question and goes straight to the answer service — no wasted router call,
# no accidental card. (A question that happens to open with one of these
# still degrades safely: the parser returns 'unknown' → no card → answer.)
_ACTION_LEAD_TOKENS = frozenset(
    {
        "schedule", "create", "add", "book", "set", "remind", "email", "draft",
        "send", "message", "note", "make", "invite", "cancel", "reschedule",
        "save", "put", "arrange", "organise", "organize", "text", "call",
    }
)

# What Naomi says when she has prepared a card (spoken, then TTS'd). Keyed by
# the card_type value the dictation builder produced.
_CONFIRMATION_BY_CARD_TYPE: dict[str, str] = {
    "create_event": "I've prepared a calendar event for you to review and approve.",
    "upsert_contact": "I've prepared a contact update for you to review and approve.",
    "draft_email": "I've prepared an email draft for you to review and approve. I won't send it.",
    "write_note": "I've prepared a note for you to review and approve.",
}
_DEFAULT_CONFIRMATION = "I've prepared an action card for you to review and approve."


@dataclass(frozen=True)
class NaomiActionResult:
    """A prepared (PENDING) action card + the line Naomi speaks about it."""

    card_id: int
    card_type: str
    spoken_confirmation: str
    llm_ms: int


def looks_like_action_request(utterance: str) -> bool:
    """True when the utterance opens with an imperative action verb.

    Pure and deterministic (tested): lowercases, strips leading punctuation,
    and checks the FIRST word against the action-verb set. Non-action
    utterances (questions) return False and skip the intent parser entirely.
    """
    stripped = utterance.strip().lstrip("\"'“‘.,! ")  # noqa: RUF001
    if not stripped:
        return False
    first_word = stripped.split(maxsplit=1)[0].lower().strip(".,!?;:")
    return first_word in _ACTION_LEAD_TOKENS


class NaomiActionIntentFlow:
    """Prepare-only action handling: parse → record → PENDING card."""

    def __init__(
        self,
        connection: aiosqlite.Connection,
        router: CompletionRouterProtocol,
        *,
        now_iso: Callable[[], str],
        clock: Callable[[], float],
    ) -> None:
        self._connection = connection
        self._router = router
        self._now_iso = now_iso
        self._clock = clock

    async def maybe_prepare_action(self, utterance: str) -> NaomiActionResult | None:
        """Return a prepared action, or None to fall through to answering.

        None means: not an action, unparseable, below the confidence floor,
        or no actionable card could be built — in every case NOTHING executes.
        """
        if not looks_like_action_request(utterance):
            return None
        started = self._clock()
        routed = await self._router.route(
            INTENT_PARSING_TASK,
            INTENT_PARSING_SYSTEM_FRAME,
            (ChatMessage(role="user", content=utterance),),  # utterance is DATA
            json_schema=DICTATION_INTENT_JSON_SCHEMA,
            max_tokens=_INTENT_MAX_TOKENS,
        )
        llm_ms = milliseconds_between(started, self._clock())
        intent = parse_intent_completion_text(routed.completion.text)
        if intent.intent_type is DictationIntentType.UNKNOWN:
            return None  # deny by default: unknown never becomes a card
        if intent.confidence < DICTATION_CONFIDENCE_FLOOR:
            # Recorded for the audit trail, but not surfaced as an action —
            # Naomi answers instead of half-confidently acting.
            await insert_dictation_intent(
                self._connection,
                ts=self._now_iso(),
                raw_text=utterance,
                intent=intent,
                provider=routed.provider,
                model=routed.model,
            )
            return None
        now = self._now_iso()
        intent_id = await insert_dictation_intent(
            self._connection,
            ts=now,
            raw_text=utterance,  # VERBATIM (fidelity mandate)
            intent=intent,
            provider=routed.provider,
            model=routed.model,
        )
        record = await get_dictation_intent(self._connection, intent_id)
        if record is None:  # pragma: no cover - just inserted, defence in depth
            return None
        built = await build_card_from_dictation_intent(
            self._connection, record=record, created_at=now
        )
        if not built.created_card_ids:
            return None  # nothing actionable (e.g. missing required field)
        card_id = built.created_card_ids[0]
        card_type = record.intent_type
        return NaomiActionResult(
            card_id=card_id,
            card_type=card_type,
            spoken_confirmation=_CONFIRMATION_BY_CARD_TYPE.get(card_type, _DEFAULT_CONFIRMATION),
            llm_ms=llm_ms,
        )
