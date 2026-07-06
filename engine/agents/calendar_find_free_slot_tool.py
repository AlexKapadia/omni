"""Tool: find the first free calendar slot inside a window (read-only).

Purpose: answer "when could this happen?" against the user's real calendar.
The Google call is a read-only freeBusy query; the slot arithmetic is a
PURE, deterministic function in this file — exact to the minute, unit-tested
at every boundary (deterministic-where-it-matters).
Pipeline position: registered in ``tool_registry`` for card type
``find_slot``; calls ``engine.google.google_api_gateway.query_free_busy``.
"""

from datetime import datetime, timedelta

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from engine.agents.agents_errors import ToolExecutionError
from engine.agents.approval_card_types import CardType
from engine.agents.tool_registry import AgentTool, ToolResult
from engine.google.google_api_gateway import BusyInterval, query_free_busy
from engine.google.google_session import GoogleSession


def _parse_iso(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


class CalendarFindFreeSlotParams(BaseModel):
    """A concrete search window and duration."""

    model_config = ConfigDict(extra="forbid")
    duration_minutes: int = Field(ge=1, le=24 * 60)
    window_start_iso: str
    window_end_iso: str
    description: str = Field(default="", max_length=500)

    @field_validator("window_start_iso", "window_end_iso")
    @classmethod
    def _must_be_iso_datetime(cls, value: str) -> str:
        _parse_iso(value)
        return value

    @model_validator(mode="after")
    def _window_must_be_ordered(self) -> "CalendarFindFreeSlotParams":
        if _parse_iso(self.window_end_iso) <= _parse_iso(self.window_start_iso):
            raise ValueError("search window end must be after its start")
        return self


def first_free_slot(
    busy: tuple[BusyInterval, ...],
    *,
    window_start: datetime,
    window_end: datetime,
    duration: timedelta,
) -> tuple[datetime, datetime] | None:
    """The earliest gap of at least ``duration`` inside the window.

    Deterministic and exact: busy intervals are clamped to the window,
    sorted, and merged; a gap of EXACTLY the duration qualifies (boundary
    inclusive). Returns None when nothing fits — an honest "no slot", never
    a squeezed or overlapping suggestion.
    """
    clamped = sorted(
        (max(_parse_iso(b.start_iso), window_start), min(_parse_iso(b.end_iso), window_end))
        for b in busy
        if _parse_iso(b.end_iso) > window_start and _parse_iso(b.start_iso) < window_end
    )
    cursor = window_start
    for start, end in clamped:
        if start - cursor >= duration:  # boundary-exact: a perfect fit counts
            return cursor, cursor + duration
        cursor = max(cursor, end)
    if window_end - cursor >= duration:
        return cursor, cursor + duration
    return None


def _narrow(params: BaseModel) -> CalendarFindFreeSlotParams:
    """Fail-closed narrowing: the registry pairs params to tools by
    construction, but a mismatch must refuse, never mis-execute."""
    if not isinstance(params, CalendarFindFreeSlotParams):
        raise ToolExecutionError(
            "CalendarFindFreeSlotParams",
            f"expected CalendarFindFreeSlotParams, got {type(params).__name__}",
        )
    return params


class CalendarFindFreeSlotTool(AgentTool):
    """Proposes a slot; writes nothing anywhere."""

    name = "calendar_find_free_slot"
    card_type = CardType.FIND_SLOT
    params_model = CalendarFindFreeSlotParams
    description = (
        "Find the earliest free slot of a given duration (minutes) between a "
        "concrete ISO-8601 window start and end on the user's calendar."
    )

    def dry_run(self, params: BaseModel) -> tuple[str, ...]:
        params = _narrow(params)
        lines = [
            f"Find {params.duration_minutes} min free",
            f"Between {params.window_start_iso} and {params.window_end_iso}",
        ]
        if params.description:
            lines.append(f"For: {params.description}")
        return tuple(lines)

    async def execute(self, params: BaseModel, google_session: GoogleSession) -> ToolResult:
        params = _narrow(params)
        busy = await query_free_busy(
            google_session,
            time_min_iso=params.window_start_iso,
            time_max_iso=params.window_end_iso,
        )
        slot = first_free_slot(
            busy,
            window_start=_parse_iso(params.window_start_iso),
            window_end=_parse_iso(params.window_end_iso),
            duration=timedelta(minutes=params.duration_minutes),
        )
        if slot is None:
            # Honest outcome, not a failure: the calendar is simply full.
            return ToolResult(
                summary_line=(
                    f"No free {params.duration_minutes} min slot between "
                    f"{params.window_start_iso} and {params.window_end_iso}"
                ),
                detail={"slot_found": False, "busy_intervals": len(busy)},
                data_sent_off_machine=(
                    "search window bounds to Google Calendar freeBusy API "
                    "(read-only; no event content sent)"
                ),
            )
        start, end = slot
        return ToolResult(
            summary_line=f"Free slot: {start.isoformat()} to {end.isoformat()}",
            detail={
                "slot_found": True,
                "slot_start_iso": start.isoformat(),
                "slot_end_iso": end.isoformat(),
            },
            data_sent_off_machine=(
                "search window bounds to Google Calendar freeBusy API "
                "(read-only; no event content sent)"
            ),
        )
