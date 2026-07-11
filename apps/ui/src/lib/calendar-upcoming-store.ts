/**
 * Fail-closed store for calendar.upcoming events from the engine poll.
 */
import { createStore, type StoreApi } from "zustand";
import { asNonEmptyString, asString } from "./untrusted-payload-guards";

export const CALENDAR_UPCOMING_EVENT = "calendar.upcoming";

export interface CalendarUpcomingEvent {
  readonly eventId: string;
  readonly title: string;
  readonly startIso: string;
  readonly endIso: string;
  readonly attendeeEmails: readonly string[];
  readonly provider: string;
}

export interface CalendarUpcomingState {
  readonly latest: CalendarUpcomingEvent | null;
}

export type CalendarUpcomingStore = StoreApi<CalendarUpcomingState>;

export const calendarUpcomingStore = createStore<CalendarUpcomingState>(() => ({
  latest: null,
}));

function parseStringArray(value: unknown): readonly string[] | null {
  if (!Array.isArray(value)) return null;
  const out: string[] = [];
  for (const item of value) {
    if (typeof item !== "string") return null;
    out.push(item);
  }
  return out;
}

function startMsOf(event: CalendarUpcomingEvent): number | null {
  const ms = Date.parse(event.startIso);
  return Number.isFinite(ms) ? ms : null;
}

/** True while the event's start is still in the future. */
export function isCalendarUpcomingActive(
  event: CalendarUpcomingEvent,
  nowMs: number = Date.now(),
): boolean {
  const startMs = startMsOf(event);
  if (startMs === null) return false;
  return startMs >= nowMs;
}

export function parseCalendarUpcomingPayload(
  payload: Record<string, unknown>,
): CalendarUpcomingEvent | null {
  const eventId = asNonEmptyString(payload["event_id"]);
  const title = asString(payload["title"]);
  const startIso = asNonEmptyString(payload["start_iso"]);
  const endIso = asNonEmptyString(payload["end_iso"]);
  const attendeeEmails = parseStringArray(payload["attendee_emails"]);
  const provider = asString(payload["provider"]) ?? "google";
  if (eventId === null || title === null || startIso === null || endIso === null) return null;
  if (attendeeEmails === null) return null;
  return { eventId, title, startIso, endIso, attendeeEmails, provider };
}

export function applyCalendarUpcoming(
  store: CalendarUpcomingStore,
  payload: Record<string, unknown>,
): void {
  // Empty poll / explicit clear: drop any stale card.
  if (payload["clear"] === true) {
    clearCalendarUpcoming(store);
    return;
  }
  const parsed = parseCalendarUpcomingPayload(payload);
  if (parsed === null) {
    // Unparseable with no clear flag: leave store alone (fail closed on bad frames).
    // But an intentionally empty upcoming list uses clear:true above.
    return;
  }
  if (!isCalendarUpcomingActive(parsed)) {
    clearCalendarUpcoming(store);
    return;
  }
  store.setState({ latest: parsed });
}

export function clearCalendarUpcoming(store: CalendarUpcomingStore): void {
  store.setState({ latest: null });
}

/**
 * Read the active upcoming event, clearing the store when the start has passed.
 */
export function getActiveCalendarUpcoming(
  store: CalendarUpcomingStore,
  nowMs: number = Date.now(),
): CalendarUpcomingEvent | null {
  const latest = store.getState().latest;
  if (latest === null) return null;
  if (!isCalendarUpcomingActive(latest, nowMs)) {
    clearCalendarUpcoming(store);
    return null;
  }
  return latest;
}
