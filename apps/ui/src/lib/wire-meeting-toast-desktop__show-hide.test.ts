/**
 * Desktop meeting toast wiring: show when detection suggests, hide otherwise;
 * Start / Not now / Stop events drive the main-window capture path.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  applyMeetingDetected,
  INITIAL_MEETING_DETECTION_STATE,
  meetingDetectionStore,
} from "./meeting-detection-store";
import { INITIAL_TRANSCRIPT_STATE, transcriptStore } from "./transcript-store";
import {
  MEETING_TOAST_DISMISS_EVENT,
  MEETING_TOAST_START_EVENT,
  MEETING_TOAST_STOP_EVENT,
  wireMeetingToastDesktop,
} from "./wire-meeting-toast-desktop";

const invoke = vi.fn(async () => undefined);
vi.mock("@tauri-apps/api/core", () => ({
  invoke: (...args: unknown[]) => invoke(...args),
}));

beforeEach(() => {
  invoke.mockClear();
  meetingDetectionStore.setState(INITIAL_MEETING_DETECTION_STATE, true);
  transcriptStore.setState(INITIAL_TRANSCRIPT_STATE, true);
});

afterEach(() => {
  // no-op
});

describe("wireMeetingToastDesktop", () => {
  it("shows the desktop toast when a suggestion arrives while idle", () => {
    const unwire = wireMeetingToastDesktop(() => {});
    applyMeetingDetected(meetingDetectionStore, {
      source: "zoom",
      reason: "zoom meeting activity detected",
      confidence: 0.9,
      dedupe_key: "zoom",
    });
    expect(invoke).toHaveBeenCalledWith("set_meeting_toast_visible", { visible: true });
    unwire();
  });

  it("hides when the suggestion is dismissed via the toast event", async () => {
    const handlers = new Map<string, (event: { payload: unknown }) => void>();
    const listen = vi.fn(async (event: string, handler: (e: { payload: unknown }) => void) => {
      handlers.set(event, handler);
      return () => {
        handlers.delete(event);
      };
    });
    const unwire = wireMeetingToastDesktop(() => {}, meetingDetectionStore, transcriptStore, listen);
    applyMeetingDetected(meetingDetectionStore, {
      source: "zoom",
      reason: "zoom meeting activity detected",
      confidence: 0.9,
      dedupe_key: "zoom",
    });
    await Promise.resolve();
    handlers.get(MEETING_TOAST_DISMISS_EVENT)?.({ payload: null });
    expect(meetingDetectionStore.getState().suggestion).toBeNull();
    expect(invoke).toHaveBeenCalledWith("set_meeting_toast_visible", { visible: false });
    unwire();
  });

  it("navigates and starts capture on the start event", async () => {
    const navigate = vi.fn();
    const handlers = new Map<string, (event: { payload: unknown }) => void>();
    const listen = vi.fn(async (event: string, handler: (e: { payload: unknown }) => void) => {
      handlers.set(event, handler);
      return () => {
        handlers.delete(event);
      };
    });
    const unwire = wireMeetingToastDesktop(navigate, meetingDetectionStore, transcriptStore, listen);
    await Promise.resolve();
    handlers.get(MEETING_TOAST_START_EVENT)?.({ payload: "Zoom meeting" });
    expect(navigate).toHaveBeenCalledTimes(1);
    // Offline engine → honest error on capture.start; still navigated.
    expect(transcriptStore.getState().errorMessage).not.toBeNull();
    unwire();
    expect(handlers.has(MEETING_TOAST_STOP_EVENT)).toBe(false); // cleaned up
  });
});
