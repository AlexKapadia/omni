/**
 * Upcoming calendar events must not linger after their start time.
 */
import { describe, expect, it, vi, afterEach } from "vitest";
import { createStore } from "zustand";
import {
  applyCalendarUpcoming,
  clearCalendarUpcoming,
  getActiveCalendarUpcoming,
  type CalendarUpcomingState,
} from "./calendar-upcoming-store";

function makeStore() {
  return createStore<CalendarUpcomingState>(() => ({ latest: null }));
}

const FUTURE = "2099-06-01T15:00:00.000Z";
const PAST = "2020-01-01T10:00:00.000Z";

afterEach(() => {
  vi.useRealTimers();
});

describe("calendar upcoming expiry", () => {
  it("apply drops / clears when start is already in the past", () => {
    const store = makeStore();
    applyCalendarUpcoming(store, {
      event_id: "e1",
      title: "Standup",
      start_iso: PAST,
      end_iso: "2020-01-01T10:30:00.000Z",
      attendee_emails: [],
      provider: "google",
    });
    expect(store.getState().latest).toBeNull();
  });

  it("apply keeps a future event", () => {
    const store = makeStore();
    applyCalendarUpcoming(store, {
      event_id: "e2",
      title: "Planning",
      start_iso: FUTURE,
      end_iso: "2099-06-01T16:00:00.000Z",
      attendee_emails: ["a@example.com"],
      provider: "outlook",
    });
    expect(store.getState().latest?.eventId).toBe("e2");
  });

  it("getActiveCalendarUpcoming returns null and clears when latest has started", () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-07-10T12:00:00.000Z"));
    const store = makeStore();
    store.setState({
      latest: {
        eventId: "stale",
        title: "Old",
        startIso: "2026-07-10T11:00:00.000Z",
        endIso: "2026-07-10T11:30:00.000Z",
        attendeeEmails: [],
        provider: "google",
      },
    });
    expect(getActiveCalendarUpcoming(store)).toBeNull();
    expect(store.getState().latest).toBeNull();
  });

  it("clearCalendarUpcoming empties the store", () => {
    const store = makeStore();
    store.setState({
      latest: {
        eventId: "x",
        title: "X",
        startIso: FUTURE,
        endIso: FUTURE,
        attendeeEmails: [],
        provider: "google",
      },
    });
    clearCalendarUpcoming(store);
    expect(store.getState().latest).toBeNull();
  });

  it("apply with empty/clear payload clears the store", () => {
    const store = makeStore();
    store.setState({
      latest: {
        eventId: "x",
        title: "X",
        startIso: FUTURE,
        endIso: FUTURE,
        attendeeEmails: [],
        provider: "google",
      },
    });
    // Empty poll / clear signal: no usable event fields.
    applyCalendarUpcoming(store, { clear: true });
    expect(store.getState().latest).toBeNull();
  });
});
