"""Tool: create a Gmail DRAFT — the engine's entire outbound-mail capability.

Purpose: turn an approved draft-email card into a draft sitting in the
user's Gmail drafts folder, where THEY decide what happens next.

DRAFT-ONLY INVARIANT (binding, claude.md §5.6 project binding): Omni never
dispatches mail. This tool calls the gateway's single draft-creation
function; no send-capable function exists in the registry, the gateway, or
anywhere else in the engine — the capability is absent from the codebase,
not merely unused, and tests scan these sources to keep it that way.

Pipeline position: registered in ``tool_registry`` for ``draft_email``.
"""

from pydantic import BaseModel, ConfigDict, Field, field_validator

from engine.agents.agents_errors import ToolExecutionError
from engine.agents.approval_card_types import CardType
from engine.agents.tool_registry import AgentTool, ToolResult
from engine.google.google_api_gateway import create_gmail_draft
from engine.google.google_session import GoogleSession


class GmailCreateDraftParams(BaseModel):
    """The draft's recipients, subject, and body, exactly as approved."""

    model_config = ConfigDict(extra="forbid")
    to: list[str] = Field(default_factory=list, max_length=10)
    subject: str = Field(min_length=1, max_length=500)
    body_text: str = Field(default="", max_length=20_000)

    @field_validator("to")
    @classmethod
    def _recipients_must_be_emails(cls, value: list[str]) -> list[str]:
        for address in value:
            if "@" not in address or address.startswith("@") or address.endswith("@"):
                # fail-closed: a name that is not an address cannot silently
                # become a recipient — the mapper/LLM must resolve it first.
                raise ValueError(f"recipient is not an email address: {address!r}")
        return value


def _narrow(params: BaseModel) -> GmailCreateDraftParams:
    """Fail-closed narrowing: the registry pairs params to tools by
    construction, but a mismatch must refuse, never mis-execute."""
    if not isinstance(params, GmailCreateDraftParams):
        raise ToolExecutionError(
            "GmailCreateDraftParams",
            f"expected GmailCreateDraftParams, got {type(params).__name__}",
        )
    return params


class GmailCreateDraftTool(AgentTool):
    """Creates the draft; the user reviews and acts on it in Gmail."""

    name = "gmail_create_draft"
    card_type = CardType.DRAFT_EMAIL
    params_model = GmailCreateDraftParams
    description = (
        "Create one Gmail DRAFT with recipients (email addresses), a subject, "
        "and a plain-text body. Drafts only — this tool cannot dispatch mail."
    )

    def dry_run(self, params: BaseModel) -> tuple[str, ...]:
        params = _narrow(params)
        to_line = ", ".join(params.to) if params.to else "(no recipient yet)"
        first_line = params.body_text.strip().splitlines()[0][:120] if params.body_text else ""
        lines = [f"Draft to: {to_line}", f"Subject: {params.subject}"]
        if first_line:
            lines.append(f"Starts: {first_line}")
        lines.append("Draft only — nothing is ever dispatched")
        return tuple(lines)

    async def execute(self, params: BaseModel, google_session: GoogleSession) -> ToolResult:
        params = _narrow(params)
        created = await create_gmail_draft(
            google_session,
            to=tuple(params.to),
            subject=params.subject,
            body_text=params.body_text,
        )
        return ToolResult(
            summary_line=f"Draft created: {params.subject}",
            detail={"draft_id": created.draft_id, "message_id": created.message_id},
            data_sent_off_machine=(
                "draft recipients, subject, and body to Gmail API (draft "
                "creation only — no dispatch capability exists)"
            ),
        )
