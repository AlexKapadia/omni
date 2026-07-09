"""Enhanced-notes pipeline: rough notes + verbatim transcript -> fused markdown.

Purpose: the one place enhancement happens. Renders the template into a
system frame, ships the sources as untrusted DATA, and sanitises the model
output before anything downstream may write it into the vault.
Pipeline position: called by ``meeting_finalization_service`` between note
creation and the enhanced-region update; talks to ``engine.router`` via
the ``enhanced_notes`` task.

Security / fidelity invariants:
- PROMPT-INJECTION DEFENCE: transcript + user notes travel ONLY in
  ``messages`` (data channel); the system frame is caller-authored and
  explicitly declares the content to be data, not instructions.
- FIDELITY: the frame instructs the model it may clean fillers/rambling in
  ITS OUTPUT but must never claim words, facts, numbers, or commitments
  not present in the sources. The sources themselves are never altered.
- OUTPUT SANITISATION (fail closed): the managed-marker sentinel is
  stripped (region-injection defence — the vault writer would refuse it),
  length is capped with an honest marker, and non-markdown garbage
  (control characters, empty output) is rejected loudly.
- The provenance footer is appended IN CODE, never trusted to the model.
"""

import re
from dataclasses import dataclass

from engine.enhance.note_templates import NoteTemplate
from engine.enhance.untrusted_content_framing import (
    DATA_NOT_INSTRUCTIONS_FRAME,
    build_meeting_data_message,
    strip_code_fence_wrapper,
)
from engine.router import ProviderRouter, TaskType

# Transcript cap for the enhancement call: the enhanced_notes route runs on
# long-context models (20 s budget), so the cap is generous; beyond it the
# middle is elided with an honest in-band marker.
_ENHANCE_TRANSCRIPT_CHARS = 120_000

# Output cap: a meeting note beyond this is runaway generation, not notes.
MAX_ENHANCED_MARKDOWN_CHARS = 60_000

# Appended in code after sanitisation (provenance is ours, not the model's).
ENHANCEMENT_FOOTER = "*Enhanced from your notes + transcript.*"

# The vault writer refuses any content carrying this sentinel (region
# injection); we strip it here so a hostile transcript cannot brick the
# enhanced-region write by tricking the model into echoing marker text.
_MANAGED_SENTINEL_PATTERN = re.compile(r"omni:managed", re.IGNORECASE)
_SENTINEL_REPLACEMENT = "omni-managed"

# Control characters other than \n and \t are not markdown — reject.
_CONTROL_CHARS_PATTERN = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


class EnhancementOutputError(Exception):
    """Model output was unusable as notes (empty, binary-ish, oversized junk)."""


@dataclass(frozen=True)
class EnhancedNotesResult:
    """Sanitised enhancement output plus the routing facts for the ledger view."""

    markdown: str  # sanitised, footer included — safe for the managed region
    template_id: str
    provider: str
    model: str
    latency_ms: int


def build_enhancement_system_frame(template: NoteTemplate, summary_language: str = "") -> str:
    """Render a template into the caller-authored instruction frame."""
    section_lines = "\n".join(
        f"## {spec.title}\n(Guidance: {spec.guidance})" for spec in template.sections
    )
    language_rule = ""
    if summary_language.strip():
        language_rule = (
            f"\nLanguage: write all output in {summary_language.strip()} "
            "(keep proper nouns from the sources as written).\n"
        )
    return (
        "You turn a meeting's rough notes and verbatim transcript into polished "
        f"meeting notes using the '{template.display_name}' format.\n\n"
        f"Structure the notes with exactly these markdown sections, in order "
        f"(omit a section only where its guidance says so):\n{section_lines}\n\n"
        f"Tone: {template.tone_rules}\n\n"
        f"{language_rule}"
        "Fidelity rules (binding):\n"
        "- Never state a fact, number, name, date, or commitment that is not "
        "present in the notes or transcript. If something is unclear, say it "
        "is unclear rather than guessing.\n"
        "- You MAY remove filler words, false starts, and rambling, and merge "
        "repetitive passages — in your output only; never quote the sources "
        "as saying words they did not say.\n"
        "- Prefer the user's own phrasing from their notes where it is usable.\n\n"
        "Output rules: markdown only, no preamble, no code fences, no HTML "
        "comments.\n\n"
        f"{DATA_NOT_INSTRUCTIONS_FRAME}"
    )


def sanitize_enhanced_markdown(raw_text: str) -> str:
    """Make model output safe for the managed region, or refuse loudly.

    Order matters: unwrap a whole-output code fence first (formatting
    noise), then strip the managed-marker sentinel (region-injection
    defence), then cap length honestly, then validate what remains.
    Raises ``EnhancementOutputError`` on unusable output (fail closed —
    the caller writes an honest "unavailable" marker instead).
    """
    text = strip_code_fence_wrapper(raw_text)
    text = _MANAGED_SENTINEL_PATTERN.sub(_SENTINEL_REPLACEMENT, text)
    text = text.strip()
    if len(text) > MAX_ENHANCED_MARKDOWN_CHARS:
        text = text[:MAX_ENHANCED_MARKDOWN_CHARS].rstrip() + "\n\n*[Output truncated.]*"
    if not text:
        raise EnhancementOutputError("model returned empty output")
    if _CONTROL_CHARS_PATTERN.search(text.replace("\r", "")):
        raise EnhancementOutputError("model output contains control characters")
    return text.replace("\r\n", "\n").replace("\r", "\n")


async def run_enhanced_notes(
    router: ProviderRouter,
    template: NoteTemplate,
    user_notes: str,
    transcript_lines: list[str],
    summary_language: str = "",
) -> EnhancedNotesResult:
    """Execute one enhancement call and return sanitised, footered markdown.

    Router errors (kill switch, whole-chain failure, misconfiguration)
    propagate to the caller — finalization isolates the step and marks the
    note honestly; this function does not swallow them.
    """
    message = build_meeting_data_message(
        user_notes, transcript_lines, max_transcript_chars=_ENHANCE_TRANSCRIPT_CHARS
    )
    routed = await router.route(
        TaskType.ENHANCED_NOTES.value,
        build_enhancement_system_frame(template, summary_language),
        (message,),
        max_tokens=8192,
    )
    markdown = sanitize_enhanced_markdown(routed.completion.text)
    return EnhancedNotesResult(
        markdown=f"{markdown}\n\n{ENHANCEMENT_FOOTER}",
        template_id=template.template_id,
        provider=routed.provider.value,
        model=routed.model,
        latency_ms=routed.latency_ms,
    )
