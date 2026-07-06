/**
 * Tests for the capture command layer: correct wire commands when the socket
 * is up, and FAIL-CLOSED honesty when it is not — no engine, no capture, and
 * the UI is told the truth.
 */
import { describe, expect, it, vi } from "vitest";
import {
  ENGINE_OFFLINE_MESSAGE,
  requestCaptureStart,
  requestCaptureStop,
} from "./capture-commands";
import { createTranscriptStore } from "./transcript-store";

describe("requestCaptureStart", () => {
  it("sends capture.start with a trimmed title and marks starting", () => {
    const store = createTranscriptStore();
    const send = vi.fn().mockReturnValue(true);
    expect(requestCaptureStart("  Vendor call  ", store, send)).toBe(true);
    expect(send).toHaveBeenCalledExactlyOnceWith("capture.start", { title: "Vendor call" });
    expect(store.getState().captureStatus).toBe("starting");
    expect(store.getState().errorMessage).toBeNull();
  });

  it("omits the title field entirely when blank (engine forbids extras/nulls)", () => {
    const store = createTranscriptStore();
    const send = vi.fn().mockReturnValue(true);
    requestCaptureStart("   ", store, send);
    expect(send).toHaveBeenCalledExactlyOnceWith("capture.start", {});
  });

  it("FAIL CLOSED: refused send -> idle + honest offline message, never 'starting'", () => {
    const store = createTranscriptStore();
    const send = vi.fn().mockReturnValue(false);
    expect(requestCaptureStart(undefined, store, send)).toBe(false);
    expect(store.getState().captureStatus).toBe("idle");
    expect(store.getState().errorMessage).toBe(ENGINE_OFFLINE_MESSAGE);
  });
});

describe("requestCaptureStop", () => {
  it("sends capture.stop and marks stopping while awaiting the engine event", () => {
    const store = createTranscriptStore();
    store.setState({ captureStatus: "live" });
    const send = vi.fn().mockReturnValue(true);
    expect(requestCaptureStop(store, send)).toBe(true);
    expect(send).toHaveBeenCalledExactlyOnceWith("capture.stop", {});
    expect(store.getState().captureStatus).toBe("stopping");
  });

  it("FAIL CLOSED: refused send keeps the live status but surfaces the truth", () => {
    const store = createTranscriptStore();
    store.setState({ captureStatus: "live" });
    const send = vi.fn().mockReturnValue(false);
    expect(requestCaptureStop(store, send)).toBe(false);
    expect(store.getState().captureStatus).toBe("live"); // no phantom stop
    expect(store.getState().errorMessage).toBe(ENGINE_OFFLINE_MESSAGE);
  });
});
