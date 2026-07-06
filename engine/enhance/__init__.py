"""Omni enhancement layer — notes fusion, extraction, and meeting finalization.

Purpose: everything that happens AFTER capture stops — fusing the user's
rough notes with the verbatim transcript into enhanced notes (templated),
extracting structured items (actions/contacts/dates/questions/commitments),
writing it all into the vault meeting note's managed regions, indexing the
meeting, and answering the Library's meetings.list / meeting.get commands.
Pipeline position: downstream of ``engine.stt`` (segments in SQLite) and
``engine.protocol`` (the meeting.finalize command); calls ``engine.router``
for model work, ``engine.vault`` for writes, ``engine.index`` for indexing.

Security / fidelity invariants upheld package-wide:
- Transcript and user-note content is UNTRUSTED DATA at every model
  boundary: it travels in ``messages``, never in ``system_frame``
  (prompt-injection defence), and model output is sanitised before any
  vault write (managed-marker sentinel stripped, length capped).
- The user's typed notes are BYTE-IDENTICAL everywhere they are stored —
  filler/rambling cleanup happens ONLY in the enhancement OUTPUT, never in
  the sources (transcription-fidelity mandate).
- Every finalization step is isolated: a failing step leaves prior steps
  intact and marks the note honestly — the raw note is never lost.
"""

from engine.enhance.enhanced_notes_pipeline import (
    EnhancedNotesResult,
    EnhancementOutputError,
    run_enhanced_notes,
    sanitize_enhanced_markdown,
)
from engine.enhance.meeting_command_dispatcher import (
    MEETING_COMMAND_NAMES,
    dispatch_meeting_command,
)
from engine.enhance.meeting_extraction_pipeline import (
    ExtractionOutcome,
    MeetingExtraction,
    format_actions_checklist,
    run_meeting_extraction,
)
from engine.enhance.meeting_finalization_result_types import (
    FinalizationResult,
    FinalizeRefusedError,
)
from engine.enhance.meeting_finalization_service import MeetingFinalizationService
from engine.enhance.note_templates import (
    AUTO_TEMPLATE_ID,
    BUILTIN_TEMPLATES,
    GENERAL_TEMPLATE_ID,
    NoteTemplate,
    SectionSpec,
    build_custom_template,
    resolve_template,
    select_template_for_transcript,
)

__all__ = [
    "AUTO_TEMPLATE_ID",
    "BUILTIN_TEMPLATES",
    "GENERAL_TEMPLATE_ID",
    "MEETING_COMMAND_NAMES",
    "EnhancedNotesResult",
    "EnhancementOutputError",
    "ExtractionOutcome",
    "FinalizationResult",
    "FinalizeRefusedError",
    "MeetingExtraction",
    "MeetingFinalizationService",
    "NoteTemplate",
    "SectionSpec",
    "build_custom_template",
    "dispatch_meeting_command",
    "format_actions_checklist",
    "resolve_template",
    "run_enhanced_notes",
    "run_meeting_extraction",
    "sanitize_enhanced_markdown",
    "select_template_for_transcript",
]
