"""Meeting extraction pipeline: transcript + notes -> validated structured items.

Purpose: the one place structured extraction happens — actions, contacts,
dates, open questions, commitments — via the router's ``live_extraction``
task with a strict JSON schema, validated by pydantic (deny by default),
retried ONCE with the validator error appended, then absent gracefully.
Pipeline position: called by ``meeting_finalization_service`` after the
enhanced-notes step; its validated payload is appended to the append-only
``extraction_results`` table for M4's approval cards.

Security invariants:
- Transcript/notes travel as untrusted DATA (messages), never in the
  system frame (prompt-injection defence).
- Model JSON is untrusted: strict pydantic validation with unknown fields
  FORBIDDEN and hard length bounds — a hostile transcript can at worst
  produce garbage items for the user to decline, never smuggle extra
  structure toward the (approval-gated) executor.
- Graceful absence: any failure returns an outcome with a plain reason;
  finalization proceeds without extraction (never blocks the note).
"""

import json
import logging
from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from engine.enhance.untrusted_content_framing import (
    DATA_NOT_INSTRUCTIONS_FRAME,
    build_meeting_data_message,
    strip_code_fence_wrapper,
)
from engine.router import ChatMessage, ProviderRouter, RouterError, TaskType

logger = logging.getLogger(__name__)

# Live-budget lane (p95 < 1.2 s per attempt): keep the excerpt lean so the
# call fits the budget; the middle is elided with an honest marker.
_EXTRACTION_TRANSCRIPT_CHARS = 12_000

_MAX_ITEMS_PER_LIST = 50  # bound every list — deny runaway output
_SHORT = 200  # bound for names/owners/dates-ish fields
_LONG = 500  # bound for titles/descriptions


class ExtractedAction(BaseModel):
    """One action item; owner/due are optional hints, never invented."""

    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=1, max_length=_LONG)
    owner: str | None = Field(default=None, max_length=_SHORT)
    due_hint: str | None = Field(default=None, max_length=_SHORT)


class ExtractedContact(BaseModel):
    """A person/company mentioned with reachable details."""

    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=_SHORT)
    phone: str | None = Field(default=None, max_length=_SHORT)
    email: str | None = Field(default=None, max_length=_SHORT)
    company: str | None = Field(default=None, max_length=_SHORT)


class ExtractedDate(BaseModel):
    """A date/time mentioned, with what it refers to."""

    model_config = ConfigDict(extra="forbid")
    when: str = Field(min_length=1, max_length=_SHORT)
    what: str = Field(min_length=1, max_length=_LONG)


class ExtractedCommitment(BaseModel):
    """Who committed to what (and when, if stated)."""

    model_config = ConfigDict(extra="forbid")
    who: str = Field(min_length=1, max_length=_SHORT)
    what: str = Field(min_length=1, max_length=_LONG)
    when: str | None = Field(default=None, max_length=_SHORT)


class MeetingExtraction(BaseModel):
    """The full validated extraction payload (persisted as-is)."""

    model_config = ConfigDict(extra="forbid")
    actions: list[ExtractedAction] = Field(default_factory=list, max_length=_MAX_ITEMS_PER_LIST)
    contacts: list[ExtractedContact] = Field(default_factory=list, max_length=_MAX_ITEMS_PER_LIST)
    dates: list[ExtractedDate] = Field(default_factory=list, max_length=_MAX_ITEMS_PER_LIST)
    open_questions: list[str] = Field(default_factory=list, max_length=_MAX_ITEMS_PER_LIST)
    commitments: list[ExtractedCommitment] = Field(
        default_factory=list, max_length=_MAX_ITEMS_PER_LIST
    )


# Strict schema shipped to the router (Gemini enforces it natively; Groq JSON
# mode relies on the frame restating it — documented client contract).
EXTRACTION_JSON_SCHEMA: dict[str, object] = MeetingExtraction.model_json_schema()


@dataclass(frozen=True)
class ExtractionOutcome:
    """What the extraction pass produced — a payload OR an honest reason."""

    extraction: MeetingExtraction | None
    failure_reason: str | None
    provider: str | None = None
    model: str | None = None
    latency_ms: int | None = None


def _system_frame() -> str:
    return (
        "You extract structured items from a meeting. Respond with JSON only, "
        "exactly this shape (all keys required, empty lists allowed):\n"
        '{"actions": [{"title": str, "owner": str|null, "due_hint": str|null}], '
        '"contacts": [{"name": str, "phone": str|null, "email": str|null, '
        '"company": str|null}], '
        '"dates": [{"when": str, "what": str}], '
        '"open_questions": [str], '
        '"commitments": [{"who": str, "what": str, "when": str|null}]}\n'
        "Only include items actually present in the content; use null for "
        "unknown optional fields; never invent names, numbers, or dates.\n"
        f"{DATA_NOT_INSTRUCTIONS_FRAME}"
    )


def _parse_and_validate(raw_text: str) -> MeetingExtraction:
    """Decode + strictly validate one model response (raises on any deviation)."""
    decoded = json.loads(strip_code_fence_wrapper(raw_text))
    return MeetingExtraction.model_validate(decoded)


async def run_meeting_extraction(
    router: ProviderRouter, user_notes: str, transcript_lines: list[str]
) -> ExtractionOutcome:
    """Run extraction with one validation retry, then degrade gracefully.

    Attempt 1: schema-framed call. If the JSON is malformed or fails
    validation, attempt 2 appends the exact validator error and the bad
    output so the model can correct itself. A second failure — or any
    router-level failure — returns an outcome with ``extraction=None`` and
    a plain reason; the caller proceeds without extraction (honest absence).
    """
    data_message = build_meeting_data_message(
        user_notes, transcript_lines, max_transcript_chars=_EXTRACTION_TRANSCRIPT_CHARS
    )
    messages: tuple[ChatMessage, ...] = (data_message,)
    last_error = "unknown validation failure"
    for attempt in (1, 2):
        try:
            routed = await router.route(
                TaskType.LIVE_EXTRACTION.value,
                _system_frame(),
                messages,
                json_schema=EXTRACTION_JSON_SCHEMA,
                max_tokens=2048,
            )
        except RouterError as exc:
            # Router-level failure (kill switch / chain exhausted / config):
            # graceful absence, with the typed error's plain-voice story.
            logger.warning("extraction unavailable: %s", exc)
            return ExtractionOutcome(extraction=None, failure_reason=str(exc))
        try:
            extraction = _parse_and_validate(routed.completion.text)
        except (ValueError, ValidationError) as exc:
            last_error = str(exc)[:2000]  # bound what we feed back / log
            if attempt == 1:
                # Retry once with the validator error appended (the model
                # sees its own bad output + the exact reason it failed).
                messages = (
                    data_message,
                    ChatMessage(role="assistant", content=routed.completion.text[:8000]),
                    ChatMessage(
                        role="user",
                        content=(
                            "Your previous JSON failed validation with this error:\n"
                            f"{last_error}\n"
                            "Return ONLY the corrected JSON object, nothing else."
                        ),
                    ),
                )
                continue
            break  # second failure: fall through to graceful absence
        return ExtractionOutcome(
            extraction=extraction,
            failure_reason=None,
            provider=routed.provider.value,
            model=routed.model,
            latency_ms=routed.latency_ms,
        )
    logger.warning("extraction JSON failed validation twice; proceeding without it")
    return ExtractionOutcome(
        extraction=None,
        failure_reason=f"model JSON failed validation twice: {last_error[:300]}",
    )


def format_actions_checklist(extraction: MeetingExtraction) -> str:
    """Render the Actions managed region as a human-readable checklist.

    Every item is explicitly *pending approval* — nothing here executes
    anything (approval-before-execute invariant; M4 reads the stored
    payload, not this rendering).
    """
    if not extraction.actions and not extraction.commitments:
        return "_No actions detected in this meeting._"
    lines: list[str] = []
    for action in extraction.actions:
        suffix = ""
        if action.owner:
            suffix += f" — {action.owner}"
        if action.due_hint:
            suffix += f" (due: {action.due_hint})"
        lines.append(f"- [ ] {action.title}{suffix}")
    for commitment in extraction.commitments:
        when = f" (when: {commitment.when})" if commitment.when else ""
        lines.append(f"- [ ] {commitment.who}: {commitment.what}{when}")
    lines.append("")
    lines.append("_Detected by Omni — pending your approval; nothing runs without it._")
    return "\n".join(lines)
