/**
 * MOCK MeetingsRepository — synthetic library rows until the M2 engine
 * repository (SQLite `meetings` table over the WS protocol) lands.
 *
 * Clearly-marked mock per the swappable-data-layer contract: same interface,
 * real-shaped data, deterministic content. Times are generated relative to
 * "now" so the day grouping and "in N min" labels exercise real date logic,
 * not frozen strings. Synthetic fixtures only — no real names or PII.
 */
import type { MeetingSummaryRow, MeetingsRepository } from "./meetings-store";

/** Small delay so the loading skeleton is a real state, not a flash. */
const MOCK_LATENCY_MS = 350;

function hoursAgoIso(hours: number): string {
  return new Date(Date.now() - hours * 3_600_000).toISOString();
}

function buildMockRows(): readonly MeetingSummaryRow[] {
  return [
    {
      id: "mock-upcoming-1",
      title: "Weekly platform sync",
      summary: "", // upcoming — nothing captured yet
      startIso: hoursAgoIso(-0.66), // ~40 minutes from now
      durationMin: 30,
    },
    {
      id: "mock-today-1",
      title: "Vendor call — Northwind",
      summary: "Renewal pricing, single-tenant ask, security review timeline.",
      startIso: hoursAgoIso(3),
      durationMin: 47,
    },
    {
      id: "mock-today-2",
      title: "Design review — capture bar",
      summary: "Breathing ring sizes, timer typography, stop button placement.",
      startIso: hoursAgoIso(6),
      durationMin: 32,
    },
    {
      id: "mock-yesterday-1",
      title: "1:1 — Elena",
      summary: "Q3 goals, conference talk draft, hiring loop feedback.",
      startIso: hoursAgoIso(27),
      durationMin: 26,
    },
    {
      id: "mock-yesterday-2",
      title: "Standup — engine team",
      summary: "WASAPI device-recovery fix shipped; VAD latency down 18 ms.",
      startIso: hoursAgoIso(30),
      durationMin: 12,
    },
    {
      id: "mock-lastweek-1",
      title: "Interview — staff engineer loop",
      summary: "Systems design round; strong on storage, follow up on routing.",
      startIso: hoursAgoIso(6 * 24),
      durationMin: 58,
    },
  ];
}

export function createMockMeetingsRepository(): MeetingsRepository {
  return {
    listMeetings: () =>
      new Promise((resolve) => {
        setTimeout(() => resolve(buildMockRows()), MOCK_LATENCY_MS);
      }),
  };
}
