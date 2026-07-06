/**
 * Adversarial tests for the meetings store: filter correctness under hostile
 * queries (regex metacharacters, unicode, whitespace), newest-first sort,
 * and the full load lifecycle including failure.
 */
import { describe, expect, it } from "vitest";
import {
  createMeetingsStore,
  filterMeetings,
  loadMeetings,
  type MeetingSummaryRow,
} from "./meetings-store";

const ROWS: readonly MeetingSummaryRow[] = [
  { id: "1", title: "Vendor call — Northwind", summary: "Renewal pricing.", startIso: "2026-07-06T14:00:00", durationMin: 47 },
  { id: "2", title: "Design review", summary: "Capture bar polish (v2).", startIso: "2026-07-06T10:00:00", durationMin: 32 },
  { id: "3", title: "1:1 — Elena", summary: "Q3 goals", startIso: "2026-07-05T09:00:00", durationMin: 26 },
];

describe("filterMeetings", () => {
  it("matches case-insensitively across title AND summary", () => {
    expect(filterMeetings(ROWS, "NORTHWIND").map((m) => m.id)).toEqual(["1"]);
    expect(filterMeetings(ROWS, "renewal").map((m) => m.id)).toEqual(["1"]);
  });

  it("empty and whitespace-only queries match everything", () => {
    expect(filterMeetings(ROWS, "")).toHaveLength(3);
    expect(filterMeetings(ROWS, "   \t ")).toHaveLength(3);
  });

  it("trims the query before matching", () => {
    expect(filterMeetings(ROWS, "  elena  ").map((m) => m.id)).toEqual(["3"]);
  });

  it("treats regex metacharacters as literal text, never a pattern", () => {
    expect(filterMeetings(ROWS, ".*")).toHaveLength(0); // would match all as regex
    expect(filterMeetings(ROWS, "(v2)").map((m) => m.id)).toEqual(["2"]); // literal parens hit
    expect(filterMeetings(ROWS, "a+")).toHaveLength(0);
  });

  it("matches non-ASCII characters exactly (em dash, digits-with-colon)", () => {
    expect(filterMeetings(ROWS, "— northwind").map((m) => m.id)).toEqual(["1"]);
    expect(filterMeetings(ROWS, "1:1").map((m) => m.id)).toEqual(["3"]);
  });

  it("returns an empty list — never throws — for a no-match query", () => {
    expect(filterMeetings(ROWS, "zzz-not-there")).toEqual([]);
  });
});

describe("loadMeetings lifecycle", () => {
  it("goes loading -> ready and sorts newest first regardless of repo order", async () => {
    const store = createMeetingsStore();
    let release: (rows: readonly MeetingSummaryRow[]) => void = () => undefined;
    const gate = new Promise<readonly MeetingSummaryRow[]>((resolve) => {
      release = resolve;
    });
    const pending = loadMeetings(store, { listMeetings: () => gate });
    expect(store.getState().status).toBe("loading"); // observable mid-flight
    release([...ROWS].reverse()); // repo returns oldest first — store must fix it
    await pending;
    expect(store.getState().status).toBe("ready");
    expect(store.getState().meetings.map((m) => m.id)).toEqual(["1", "2", "3"]);
  });

  it("a rejecting repository lands in error with the real message", async () => {
    const store = createMeetingsStore();
    await loadMeetings(store, {
      listMeetings: () => Promise.reject(new Error("db locked")),
    });
    expect(store.getState().status).toBe("error");
    expect(store.getState().errorMessage).toBe("db locked");
    expect(store.getState().meetings).toHaveLength(0); // no phantom rows on failure
  });

  it("a non-Error rejection still produces honest error copy", async () => {
    const store = createMeetingsStore();
    // eslint-style disable not needed: rejecting with a string is the attack.
    await loadMeetings(store, { listMeetings: () => Promise.reject("boom") });
    expect(store.getState().status).toBe("error");
    expect(store.getState().errorMessage).toBe("Could not load meetings.");
  });

  it("retry after error recovers to ready", async () => {
    const store = createMeetingsStore();
    await loadMeetings(store, { listMeetings: () => Promise.reject(new Error("x")) });
    await loadMeetings(store, { listMeetings: () => Promise.resolve(ROWS) });
    expect(store.getState().status).toBe("ready");
    expect(store.getState().errorMessage).toBeNull();
    expect(store.getState().meetings).toHaveLength(3);
  });
});
