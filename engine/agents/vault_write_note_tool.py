"""Tool: write a new note into the vault Inbox (engine.vault only, no Google).

Purpose: land an approved "write this down" action as a NEW vault note.
Purely local — this tool has no Google surface at all and keeps working
with the kill switch engaged (fail closed on egress, never on the user's
own data).
Pipeline position: registered in ``tool_registry`` for ``write_note``;
delegates to ``engine.vault.inbox_dictation_writer``-style creation via the
same sanitizer/atomic-write primitives.

Security invariant: creation-only — collision suffixing means an existing
note is never overwritten (never-edit-user-content).
"""

from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from engine.agents.agents_errors import ToolExecutionError
from engine.agents.approval_card_types import CardType
from engine.agents.tool_registry import AgentTool, ToolResult
from engine.google.google_session import GoogleSession
from engine.vault.atomic_markdown_file_io import write_file_atomically
from engine.vault.filename_sanitizer import next_available_note_path, sanitize_filename_stem
from engine.vault.frontmatter_codec import emit_frontmatter
from engine.vault.vault_paths import INBOX_FOLDER, ensure_vault_subfolder


class VaultWriteNoteParams(BaseModel):
    """A new note's title and body, exactly as approved."""

    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=1, max_length=200)
    body_markdown: str = Field(min_length=1, max_length=20_000)


def _narrow(params: BaseModel) -> VaultWriteNoteParams:
    """Fail-closed narrowing: the registry pairs params to tools by
    construction, but a mismatch must refuse, never mis-execute."""
    if not isinstance(params, VaultWriteNoteParams):
        raise ToolExecutionError(
            "VaultWriteNoteParams", f"expected VaultWriteNoteParams, got {type(params).__name__}"
        )
    return params


class VaultWriteNoteTool(AgentTool):
    """Creates ``Inbox/{title}.md`` with honest provenance frontmatter."""

    name = "vault_write_note"
    card_type = CardType.WRITE_NOTE
    params_model = VaultWriteNoteParams
    description = (
        "Create one new markdown note (title + body) in the vault's Inbox "
        "folder. Local only; never overwrites an existing note."
    )

    def __init__(self, vault_root: Path) -> None:
        self._vault_root = vault_root

    def dry_run(self, params: BaseModel) -> tuple[str, ...]:
        params = _narrow(params)
        first_line = params.body_markdown.strip().splitlines()[0][:120]
        return (f"Note: {params.title}", f"Starts: {first_line}", "Saved to Inbox/")

    async def execute(self, params: BaseModel, google_session: GoogleSession) -> ToolResult:
        params = _narrow(params)
        folder = ensure_vault_subfolder(self._vault_root, INBOX_FOLDER)
        # Untrusted title -> sanitized stem; collisions get " (n)" suffixes
        # so nothing is ever overwritten (never-edit-user-content).
        path = next_available_note_path(folder, sanitize_filename_stem(params.title))
        date_iso = datetime.now(tz=UTC).date().isoformat()
        frontmatter = emit_frontmatter({"date": date_iso, "source": "approved-card"})
        write_file_atomically(path, f"{frontmatter}\n{params.body_markdown.rstrip()}\n")
        return ToolResult(
            summary_line=f"Note saved: {path.name}",
            detail={"note_path": str(path)},
            data_sent_off_machine="",  # local-only invariant: nothing egressed
        )
