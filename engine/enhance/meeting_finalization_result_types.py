"""Result/refusal types for meeting finalization (the reply-payload contract).

Purpose: the two types every consumer of finalization shares — the honest
per-run result whose ``to_payload()`` field names are pinned by the UI's
TypeScript mirror, and the fail-closed refusal error raised before any
write happens. Split from the service so the orchestration file stays
within the repo's size discipline and the wire contract is findable alone.
Pipeline position: produced by
``engine.enhance.meeting_finalization_service``; consumed by
``meeting_command_dispatcher`` (reply shaping) and tests.
"""

from dataclasses import dataclass, field


class FinalizeRefusedError(Exception):
    """The finalize request itself is invalid (unknown/unfinished/duplicate).

    Raised ONLY before any write or event (fail closed): the caller can
    surface the plain-voice reason and safely retry after fixing it.
    """


@dataclass(frozen=True)
class FinalizationResult:
    """The honest account of one finalization run (reply payload source)."""

    meeting_id: str
    note_path: str  # vault-relative posix path of the created note
    template_id: str
    enhance_ok: bool
    extraction_ok: bool
    indexed_chunks: int
    warnings: tuple[str, ...] = field(default=())

    def to_payload(self) -> dict[str, object]:
        """The ``ok`` reply payload — field names pinned by the TS mirror."""
        return {
            "meeting_id": self.meeting_id,
            "note_path": self.note_path,
            "template_id": self.template_id,
            "enhance_ok": self.enhance_ok,
            "extraction_ok": self.extraction_ok,
            "indexed_chunks": self.indexed_chunks,
            "warnings": list(self.warnings),
        }
