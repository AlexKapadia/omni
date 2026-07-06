"""Tool: create one Google Calendar event from an approved card.

Purpose: the ONLY code path that writes to the user's calendar. Parameters
are fully concrete (ISO datetimes, validated emails) — resolving natural
language like "Friday at 1" happens BEFORE this tool, in the executor's
deterministic-first mapping (LLM fallback), so what executes is exact.
Pipeline position: registered in ``tool_registry`` for card type
``create_event``; calls ``engine.google.google_api_gateway``.

Security invariant: runs only via the card executor on an approved card;
the gateway underneath enforces the kill switch before any egress.
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from engine.agents.agents_errors import ToolExecutionError
from engine.agents.approval_card_types import CardType
from engine.agents.tool_registry import AgentTool, ToolResult
from engine.google.google_api_gateway import create_calendar_event
from engine.google.google_session import GoogleSession


def _parse_iso(value: str) -> datetime:
    """Strict ISO-8601 parse ('Z' accepted); raises ValueError otherwise."""
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


class CalendarCreateEventParams(BaseModel):
    """Concrete event parameters — nothing fuzzy survives validation."""

    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=1, max_length=500)
    start_iso: str
    end_iso: str
    description: str = Field(default="", max_length=20_000)
    attendee_emails: list[str] = Field(default_factory=list, max_length=20)

    @field_validator("start_iso", "end_iso")
    @classmethod
    def _must_be_iso_datetime(cls, value: str) -> str:
        _parse_iso(value)  # raises on garbage — fail closed, never guess
        return value

    @field_validator("attendee_emails")
    @classmethod
    def _must_look_like_emails(cls, value: list[str]) -> list[str]:
        for email in value:
            # Minimal shape check: inviting a non-address would error at
            # Google anyway; refusing here keeps the preview honest.
            if "@" not in email or email.startswith("@") or email.endswith("@"):
                raise ValueError(f"attendee is not an email address: {email!r}")
        return value

    @model_validator(mode="after")
    def _end_after_start(self) -> "CalendarCreateEventParams":
        if _parse_iso(self.end_iso) <= _parse_iso(self.start_iso):
            raise ValueError("event end must be after its start")
        return self


def _narrow(params: BaseModel) -> CalendarCreateEventParams:
    """Fail-closed narrowing: the registry pairs params to tools by
    construction, but a mismatch must refuse, never mis-execute."""
    if not isinstance(params, CalendarCreateEventParams):
        raise ToolExecutionError(
            "CalendarCreateEventParams",
            f"expected CalendarCreateEventParams, got {type(params).__name__}",
        )
    return params


class CalendarCreateEventTool(AgentTool):
    """Creates the event exactly as previewed on the approved card."""

    name = "calendar_create_event"
    card_type = CardType.CREATE_EVENT
    params_model = CalendarCreateEventParams
    description = (
        "Create one Google Calendar event with a concrete ISO-8601 start and "
        "end, an exact title, and optional attendee email addresses."
    )

    def dry_run(self, params: BaseModel) -> tuple[str, ...]:
        """The card preview: exactly what will be created, nothing implied."""
        params = _narrow(params)
        lines = [f"Event: {params.title}", f"From {params.start_iso} to {params.end_iso}"]
        if params.attendee_emails:
            lines.append("Invite: " + ", ".join(params.attendee_emails))
        if params.description:
            lines.append(f"Notes: {params.description[:120]}")
        return tuple(lines)

    async def execute(self, params: BaseModel, google_session: GoogleSession) -> ToolResult:
        params = _narrow(params)
        created = await create_calendar_event(
            google_session,
            title=params.title,
            start_iso=params.start_iso,
            end_iso=params.end_iso,
            description=params.description,
            attendee_emails=tuple(params.attendee_emails),
        )
        return ToolResult(
            summary_line=f"Event created: {params.title} ({params.start_iso})",
            detail={"event_id": created.event_id, "html_link": created.html_link},
            # §5.6 minimum-data account: exactly the fields that left the box.
            data_sent_off_machine=(
                "event title, start/end time, description, and attendee emails "
                "to Google Calendar API"
            ),
        )
