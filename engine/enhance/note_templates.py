"""Enhanced-notes templates: Auto, General, 1:1, Sales, Interview, Standup + custom.

Purpose: the typed template system the enhancement pipeline renders
against. A template is a structure — ordered sections, per-section
guidance, tone rules — never a blob of prose, so section order and
guidance are testable data. "Auto" is not a template: it is the routed,
cheap LLM decision of WHICH built-in fits the transcript best.
Pipeline position: consumed by ``enhanced_notes_pipeline`` (renders the
system frame from a template) and by ``meeting_finalization_service``
(resolves the id arriving on the ``meeting.finalize`` command).

Security invariants:
- Auto-selection sends transcript content as untrusted DATA (messages),
  never inside the system frame; a hostile transcript can at worst pick a
  different template, never change the task.
- Selection fails closed to the General template on ANY router error or
  malformed model output — a template decision must never block notes.
"""

import json
import logging
from dataclasses import dataclass

from engine.enhance.untrusted_content_framing import (
    DATA_NOT_INSTRUCTIONS_FRAME,
    build_meeting_data_message,
    strip_code_fence_wrapper,
)
from engine.router import ProviderRouter, RouterError, TaskType

logger = logging.getLogger(__name__)

# Template ids are lowercase snake, pinned — the WS command carries them.
AUTO_TEMPLATE_ID = "auto"
GENERAL_TEMPLATE_ID = "general"

# Transcript excerpt cap for the (cheap, live-budget) selection call.
_SELECTION_EXCERPT_CHARS = 4_000


@dataclass(frozen=True)
class SectionSpec:
    """One section of an enhanced note: its heading and writing guidance."""

    title: str
    guidance: str


@dataclass(frozen=True)
class NoteTemplate:
    """A typed enhanced-notes template (structure, guidance, tone)."""

    template_id: str
    display_name: str
    sections: tuple[SectionSpec, ...]
    tone_rules: str


def _t(template_id: str, name: str, tone: str, *sections: tuple[str, str]) -> NoteTemplate:
    """Compact builder for the built-in table below."""
    return NoteTemplate(
        template_id=template_id,
        display_name=name,
        sections=tuple(SectionSpec(title=t, guidance=g) for t, g in sections),
        tone_rules=tone,
    )


BUILTIN_TEMPLATES: dict[str, NoteTemplate] = {
    t.template_id: t
    for t in (
        _t(
            GENERAL_TEMPLATE_ID,
            "General meeting",
            "Neutral, concise, factual. Prefer short bullets over prose.",
            ("Summary", "2-4 sentences: what the meeting was about and what changed."),
            ("Key Points", "The substantive points discussed, grouped by topic."),
            ("Decisions", "Only decisions actually made; omit the section if none."),
            ("Next Steps", "Concrete follow-ups mentioned, with owners where stated."),
        ),
        _t(
            "one_on_one",
            "1:1",
            "Personal, direct, supportive. Keep names as spoken.",
            ("Summary", "1-3 sentences on the overall thread of the conversation."),
            ("Their Updates", "What the other person raised: wins, blockers, concerns."),
            ("My Updates", "What the user raised or committed to."),
            ("Feedback & Growth", "Feedback exchanged, coaching, career topics; omit if none."),
            ("Follow-ups", "Agreed follow-ups with who owns each."),
        ),
        _t(
            "sales",
            "Sales call",
            "Sharp, deal-focused. Quantities and dates exactly as stated — never invent numbers.",
            ("Summary", "2-3 sentences: the deal, the stage, how the call moved it."),
            ("Customer Needs & Pain", "Needs, pains, and requirements in the customer's terms."),
            ("Objections & Risks", "Objections raised and how they were handled; open risks."),
            ("Pricing & Commercials", "Any pricing, terms, or budget signals; omit if none."),
            ("Next Steps", "Agreed next steps with owner and timing."),
        ),
        _t(
            "interview",
            "Interview",
            "Evidence-based and fair: cite what the candidate actually said or did.",
            ("Summary", "2-3 sentences: role context and overall impression."),
            ("Strengths", "Observed strengths, each tied to something said in the interview."),
            ("Concerns", "Gaps or concerns, each tied to evidence, never speculation."),
            ("Questions & Answers", "Notable questions asked and the gist of the answers."),
            ("Follow-ups", "Areas the next interviewer should probe."),
        ),
        _t(
            "standup",
            "Standup",
            "Terse. One line per item; no prose paragraphs.",
            ("Done", "What was reported finished."),
            ("In Progress", "What is being worked on."),
            ("Blockers", "Blockers raised and who is unblocking them; omit if none."),
            ("Next Steps", "Anything agreed for after the standup."),
        ),
    )
}


def build_custom_template(
    template_id: str,
    display_name: str,
    sections: list[tuple[str, str]],
    tone_rules: str,
) -> NoteTemplate:
    """Construct a validated custom template (Settings surface, later UI).

    Bounds keep a template renderable inside one system frame; validation
    fails closed with ValueError rather than producing a degenerate frame.
    """
    is_snake = template_id.replace("_", "").isalnum() and template_id.lower() == template_id
    if not template_id or not is_snake:
        raise ValueError(f"template_id must be lowercase snake_case, got {template_id!r}")
    if template_id in BUILTIN_TEMPLATES or template_id == AUTO_TEMPLATE_ID:
        raise ValueError(f"template_id {template_id!r} collides with a built-in")
    if not display_name.strip():
        raise ValueError("display_name must be non-empty")
    if not 1 <= len(sections) <= 12:
        raise ValueError("a template needs between 1 and 12 sections")
    specs: list[SectionSpec] = []
    for title, guidance in sections:
        if not title.strip() or not guidance.strip():
            raise ValueError("every section needs a non-empty title and guidance")
        if len(title) > 80 or len(guidance) > 500:
            raise ValueError("section title/guidance exceed the 80/500 character bounds")
        specs.append(SectionSpec(title=title.strip(), guidance=guidance.strip()))
    if len(tone_rules) > 500:
        raise ValueError("tone_rules exceeds 500 characters")
    return NoteTemplate(
        template_id=template_id,
        display_name=display_name.strip(),
        sections=tuple(specs),
        tone_rules=tone_rules.strip(),
    )


def resolve_template(template_id: str | None) -> NoteTemplate | None:
    """Resolve a command's template id: a NoteTemplate, or None meaning AUTO.

    Deny by default: an id that is neither "auto"/absent nor a built-in
    raises ValueError (the WS layer turns it into an invalid-payload reply)
    rather than silently substituting a different template.
    """
    if template_id is None or template_id == AUTO_TEMPLATE_ID:
        return None  # caller runs auto-selection
    template = BUILTIN_TEMPLATES.get(template_id)
    if template is None:
        raise ValueError(f"unknown template id: {template_id!r}")
    return template


# JSON schema for the selection call (Groq JSON-mode: the frame restates it).
_SELECTION_JSON_SCHEMA: dict[str, object] = {
    "type": "object",
    "properties": {"template_id": {"type": "string", "enum": sorted(BUILTIN_TEMPLATES)}},
    "required": ["template_id"],
    "additionalProperties": False,
}


async def select_template_for_transcript(
    router: ProviderRouter, user_notes: str, transcript_lines: list[str]
) -> NoteTemplate:
    """Auto mode: ask a cheap routed model which built-in template fits.

    Routed as ``intent_parsing`` (the live/cheap classification lane —
    picking a note format IS parsing the meeting's intent). Fails closed to
    the General template on any router error, malformed JSON, or an id
    outside the enum — template choice must never block finalization.
    """
    choices = ", ".join(
        f'"{t.template_id}" ({t.display_name})' for t in BUILTIN_TEMPLATES.values()
    )
    system_frame = (
        "You classify a meeting so the right note template is used. "
        f"Choose exactly one template id from: {choices}. "
        'Respond with JSON only: {"template_id": "<id>"}. '
        f"{DATA_NOT_INSTRUCTIONS_FRAME}"
    )
    message = build_meeting_data_message(
        user_notes, transcript_lines, max_transcript_chars=_SELECTION_EXCERPT_CHARS
    )
    try:
        routed = await router.route(
            TaskType.INTENT_PARSING.value,
            system_frame,
            (message,),
            json_schema=_SELECTION_JSON_SCHEMA,
            max_tokens=64,
        )
        decoded = json.loads(strip_code_fence_wrapper(routed.completion.text))
        selected = decoded.get("template_id") if isinstance(decoded, dict) else None
    except (RouterError, ValueError):
        # Fail closed to General: notes still get made, honestly generic.
        logger.warning("template auto-selection unavailable; using the general template")
        return BUILTIN_TEMPLATES[GENERAL_TEMPLATE_ID]
    template = BUILTIN_TEMPLATES.get(selected) if isinstance(selected, str) else None
    if template is None:
        # Deny by default: an out-of-enum id (or injected nonsense) cannot
        # steer the pipeline anywhere except the safe generic template.
        logger.warning("template auto-selection returned %r; using general", selected)
        return BUILTIN_TEMPLATES[GENERAL_TEMPLATE_ID]
    return template
