/**
 * Behaviour tests for the status footer: correct copy per status, exact uptime
 * formatting at boundaries, and honest latency display (never a stale number
 * while disconnected).
 */
import { afterEach, beforeAll, beforeEach, describe, expect, it } from "vitest";
import { act, cleanup, render, screen } from "@testing-library/react";
import { StatusFooter, formatUptime } from "./status-footer";
import { engineStatusStore, INITIAL_ENGINE_STATUS } from "../lib/engine-status-store";

beforeAll(() => {
  // jsdom has no matchMedia; framer-motion's useReducedMotion needs it.
  window.matchMedia ??= ((query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: () => undefined,
    removeListener: () => undefined,
    addEventListener: () => undefined,
    removeEventListener: () => undefined,
    dispatchEvent: () => false,
  })) as typeof window.matchMedia;
});

beforeEach(() => {
  engineStatusStore.setState(INITIAL_ENGINE_STATUS, true);
});

afterEach(() => {
  cleanup();
});

describe("formatUptime is exact at every boundary", () => {
  it.each<[number, string]>([
    [0, "0s"],
    [59, "59s"],
    [59.9, "59s"], // floors, never rounds up into a fake minute
    [60, "1m 0s"],
    [61, "1m 1s"],
    [3599, "59m 59s"],
    [3600, "1h 0m 0s"],
    [3671, "1h 1m 11s"],
    [86400, "24h 0m 0s"],
  ])("formatUptime(%d) === %s", (input, expected) => {
    expect(formatUptime(input)).toBe(expected);
  });
});

describe("StatusFooter renders live engine state", () => {
  it("shows connecting copy and no latency before the engine is proven alive", () => {
    render(<StatusFooter />);
    expect(screen.getByText("Starting…")).toBeTruthy();
    expect(screen.getByText("— ms")).toBeTruthy();
    expect(screen.queryByText(/^up /)).toBeNull();
  });

  it("shows version, uptime and latency once connected", () => {
    engineStatusStore.setState({
      status: "connected",
      uptimeS: 65,
      engineVersion: "0.1.0",
      lastLatencyMs: 42.4,
      sttReady: true,
    });
    render(<StatusFooter />);
    expect(screen.getByText("Ready")).toBeTruthy();
    expect(screen.getByText("v0.1.0")).toBeTruthy();
    expect(screen.getByText("up 1m 5s")).toBeTruthy();
    expect(screen.getByText("42 ms")).toBeTruthy(); // rounded, unit visible
  });

  it("never shows stale uptime or latency after a disconnect", () => {
    engineStatusStore.setState({
      status: "disconnected",
      uptimeS: 65,
      engineVersion: "0.1.0",
      lastLatencyMs: 42,
      sttReady: true,
    });
    render(<StatusFooter />);
    expect(screen.getByText("Omni Steroid isn’t running")).toBeTruthy();
    // Version is identity (still true); uptime/latency are liveness (now unknown).
    expect(screen.queryByText("up 1m 5s")).toBeNull();
    expect(screen.getByText("— ms")).toBeTruthy();
  });

  it("re-renders when the store changes underneath it", () => {
    render(<StatusFooter />);
    expect(screen.getByText("Starting…")).toBeTruthy();
    act(() => {
      engineStatusStore.setState({
        status: "connected",
        uptimeS: 1,
        engineVersion: "0.1.0",
        lastLatencyMs: 5,
        sttReady: false,
      });
    });
    expect(screen.getByText("Ready")).toBeTruthy();
    expect(screen.getByText("5 ms")).toBeTruthy();
  });
});
