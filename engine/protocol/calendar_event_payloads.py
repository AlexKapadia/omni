"""Protocol payloads for calendar poll events."""

EVENT_CALENDAR_UPCOMING = "calendar.upcoming"


def build_calendar_upcoming_payload(
    *,
    event_id: str,
    title: str,
    start_iso: str,
    end_iso: str,
    attendee_emails: tuple[str, ...],
) -> dict[str, object]:
    return {
        "event_id": event_id,
        "title": title,
        "start_iso": start_iso,
        "end_iso": end_iso,
        "attendee_emails": list(attendee_emails),
    }
