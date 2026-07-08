/**
 * State-coverage + behaviour tests for the Library screen: loading shimmer,
 * error with a working retry, empty, populated with day groups, live search
 * filtering, and the no-matches state. Search must actually filter — a
 * decorative input is a defect.
 */
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { LibraryScreen } from "./library-screen";
import {
  INITIAL_MEETINGS_STATE,
  meetingsStore,
  type MeetingSummaryRow,
} from "../lib/meetings-store";
import { installJsdomMatchMediaShim } from "../test-support/install-jsdom-match-media-shim";

beforeAll(installJsdomMatchMediaShim);

beforeEach(() => {
  meetingsStore.setState(INITIAL_MEETINGS_STATE, true);
});

afterEach(cleanup);

const onStartCapture = vi.fn();

function rows(): readonly MeetingSummaryRow[] {
  const hoursAgo = (h: number) => new Date(Date.now() - h * 3_600_000).toISOString();
  return [
    { id: "1", title: "Vendor call — Northwind", summary: "Renewal pricing.", startIso: hoursAgo(2), durationMin: 47 },
    { id: "2", title: "Design review", summary: "Capture bar.", startIso: hoursAgo(3), durationMin: 32 },
    { id: "3", title: "1:1 — Elena", summary: "Q3 goals.", startIso: hoursAgo(26), durationMin: 26 },
  ];
}

describe("LibraryScreen states", () => {
  it("LOADING: shows the shimmer skeleton, never rows", () => {
    // Repository that never resolves — the screen must hold the loading state.
    render(<LibraryScreen repository={{ listMeetings: () => new Promise(() => undefined) }} onStartCapture={onStartCapture} />);
    expect(screen.getByRole("status", { name: "Loading" })).toBeTruthy();
    expect(screen.queryByText("Vendor call — Northwind")).toBeNull();
  });

  it("ERROR: shows the message and the retry button actually reloads", async () => {
    meetingsStore.setState({ status: "error", errorMessage: "db locked" });
    const repository = { listMeetings: vi.fn().mockResolvedValue(rows()) };
    render(<LibraryScreen repository={repository} onStartCapture={onStartCapture} />);
    expect(screen.getByText("Could not load your meetings.")).toBeTruthy();
    expect(screen.getByText("db locked")).toBeTruthy();
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Retry loading" }));
    });
    expect(repository.listMeetings).toHaveBeenCalledTimes(1);
    expect(screen.getByText("Vendor call — Northwind")).toBeTruthy();
  });

  it("EMPTY: says what will happen and offers capture", () => {
    meetingsStore.setState({ status: "ready", meetings: [] });
    render(<LibraryScreen onStartCapture={onStartCapture} />);
    expect(screen.getByText("No meetings yet")).toBeTruthy();
    expect(screen.getByText(/two labelled transcript streams/)).toBeTruthy();
    fireEvent.click(screen.getAllByRole("button", { name: "Start capture" })[1]!);
    expect(onStartCapture).toHaveBeenCalled();
  });

  it("POPULATED: renders every row, day groups, and the computed meta line", () => {
    vi.setSystemTime(new Date("2026-07-07T15:00:00"));
    meetingsStore.setState({ status: "ready", meetings: rows() });
    render(<LibraryScreen onStartCapture={onStartCapture} />);
    expect(screen.getByText("Vendor call — Northwind")).toBeTruthy();
    expect(screen.getByText("Design review")).toBeTruthy();
    expect(screen.getByText("1:1 — Elena")).toBeTruthy();
    expect(screen.getByText("Today")).toBeTruthy();
    expect(screen.getByText("Yesterday")).toBeTruthy();
    // 47 + 32 + 26 = 105 min = 1 h 45 min — computed, exact.
    expect(screen.getByText(/3 meetings · 1 h 45 min captured/)).toBeTruthy();
    vi.useRealTimers();
  });
});

describe("LibraryScreen search", () => {
  it("typing filters the visible rows immediately", () => {
    meetingsStore.setState({ status: "ready", meetings: rows() });
    render(<LibraryScreen onStartCapture={onStartCapture} />);
    fireEvent.change(screen.getByRole("searchbox", { name: "Search meetings" }), {
      target: { value: "northwind" },
    });
    expect(screen.getByText("Vendor call — Northwind")).toBeTruthy();
    expect(screen.queryByText("Design review")).toBeNull();
    expect(screen.queryByText("1:1 — Elena")).toBeNull();
  });

  it("a no-match query shows the honest no-matches state, then recovers", () => {
    meetingsStore.setState({ status: "ready", meetings: rows() });
    render(<LibraryScreen onStartCapture={onStartCapture} />);
    const input = screen.getByRole("searchbox", { name: "Search meetings" });
    fireEvent.change(input, { target: { value: "zzz" } });
    expect(screen.getByText("No meetings match “zzz”.")).toBeTruthy();
    fireEvent.change(input, { target: { value: "" } });
    expect(screen.getByText("Design review")).toBeTruthy();
  });
});
