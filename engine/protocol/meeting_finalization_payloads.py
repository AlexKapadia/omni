"""Payload models + message names for the M2 meeting-finalization WS surface.

Purpose: the pinned shapes of the M2 additions to protocol v1 — the
``meeting.finalize`` / ``meetings.list`` / ``meeting.get`` commands and the
``enhance.started`` / ``enhance.ready`` / ``enhance.failed`` events. The
UI's TypeScript mirror is built against these exact field names; changes
are breaking. Everything here is ADDITIVE to protocol v1.
Pipeline position: between ``engine.enhance`` (producer/consumer) and
``engine.protocol.websocket_envelope`` (wire form).

Security invariants:
- Command payloads are validated strictly (unknown fields rejected — deny
  by default), with hard length bounds so a hostile client cannot stuff
  megabytes through one field (the envelope's 64 KiB cap is the outer
  wall; these bounds keep honest payloads honest).
- ``notepad_text`` is the user's rough notes and is carried VERBATIM —
  no trimming, no normalisation — because the vault write must be
  byte-identical to what the user typed (fidelity mandate).
"""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

# --- message names (TS-mirror-compatible, dot-namespaced like `capture.start`).
COMMAND_MEETING_FINALIZE = "meeting.finalize"
COMMAND_MEETINGS_LIST = "meetings.list"
COMMAND_MEETING_GET = "meeting.get"
COMMAND_MEETING_EXPORT = "meeting.export"
COMMAND_TRANSCRIPT_SEGMENT_UPDATE = "transcript.segment.update"
COMMAND_IMPORT_MEDIA = "import.media"
COMMAND_MEETING_RETRANSCRIBE = "meeting.retranscribe"
COMMAND_MEETING_TEXT_REPLACE = "meeting.text.replace"
EVENT_ENHANCE_STARTED = "enhance.started"
EVENT_ENHANCE_READY = "enhance.ready"
EVENT_ENHANCE_FAILED = "enhance.failed"

# Bound on the notepad text a single finalize command may carry. WHY 20_000:
# the envelope parser rejects frames over 64 KiB BEFORE JSON decoding; JSON
# string escaping can inflate text ~2x, so 20k characters keeps a legitimate
# worst-case frame safely under the wire cap while covering realistic notes.
MAX_NOTEPAD_TEXT_CHARS = 20_000


class MeetingFinalizeCommandPayload(BaseModel):
    """Payload of ``meeting.finalize`` (client -> engine).

    ``extra="forbid"``: unknown fields rejected — deny by default.
    ``notepad_text`` travels verbatim (see module docstring).
    """

    model_config = ConfigDict(extra="forbid")

    meeting_id: str = Field(min_length=1, max_length=128)
    notepad_text: str = Field(max_length=MAX_NOTEPAD_TEXT_CHARS)
    # Optional template id ("auto", "one_on_one", ...); None means auto.
    template: str | None = Field(default=None, max_length=64)


class MeetingsListCommandPayload(BaseModel):
    """Payload of ``meetings.list`` — deliberately empty."""

    model_config = ConfigDict(extra="forbid")


class MeetingGetCommandPayload(BaseModel):
    """Payload of ``meeting.get`` (client -> engine)."""

    model_config = ConfigDict(extra="forbid")

    meeting_id: str = Field(min_length=1, max_length=128)


class MeetingExportCommandPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    meeting_id: str = Field(min_length=1, max_length=128)
    format: str = Field(pattern=r"^(srt|vtt|txt|pdf|docx|md)$")


class TranscriptSegmentUpdatePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    meeting_id: str = Field(min_length=1, max_length=128)
    segment_id: str = Field(min_length=1, max_length=128)
    text: str = Field(min_length=1, max_length=20_000)


class ImportMediaCommandPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str = Field(min_length=1, max_length=1024)
    title: str | None = Field(default=None, max_length=200)
    identify_speakers: bool = False


EVENT_IMPORT_MEDIA_PROGRESS = "import.media.progress"


class MeetingRetranscribeCommandPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    meeting_id: str = Field(min_length=1, max_length=128)


class MeetingTextReplacePayload(BaseModel):
    """Find/replace across transcript segments and/or enhanced notes."""

    model_config = ConfigDict(extra="forbid")

    meeting_id: str = Field(min_length=1, max_length=128)
    find: str = Field(min_length=1, max_length=500)
    replace: str = Field(max_length=500)
    target: str = Field(pattern=r"^(transcript|enhanced_notes|both)$")


def build_import_media_progress_payload(stage: str, fraction: float) -> dict[str, Any]:
    return {"stage": stage, "fraction": fraction}


def build_enhance_started_payload(meeting_id: str) -> dict[str, Any]:
    """``enhance.started``: finalization began for ``meeting_id``."""
    return {"meeting_id": meeting_id}


def build_enhance_ready_payload(meeting_id: str, note_path: str) -> dict[str, Any]:
    """``enhance.ready``: enhanced notes landed in the vault note."""
    return {"meeting_id": meeting_id, "note_path": note_path}


def build_enhance_failed_payload(meeting_id: str, reason: str) -> dict[str, Any]:
    """``enhance.failed``: enhancement could not run; ``reason`` is a plain,
    already-redacted sentence (never key material, never raw model output)."""
    return {"meeting_id": meeting_id, "reason": reason}
