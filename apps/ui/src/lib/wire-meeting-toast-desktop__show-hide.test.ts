/**
 * Desktop meeting toast wiring: show when detection suggests, hide otherwise;
 * Start / Not now / Stop / Keep going events drive the main-window path.
 * Always invokes set_meeting_toast_visible (no lastVisible cache).
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  applyCaptureSuggestStop,
  applyMeetingDetected,
  clearStopHint,
  INITIAL_MEETING_DETECTION_STATE,
  meetingDetectionStore,
} from "./meeting-detection-store";
import { INITIAL_TRANSCRIPT_STATE, transcriptStore } from "./transcript-store";
import {
  MEETING_TOAST_DISMISS_EVENT,
  MEETING_TOAST_KEEP_GOING_EVENT,
  MEETING_TOAST_START_EVENT,
  MEETING_TOAST_STOP_EVENT,
  wireMeetingToastDesktop,
} from "./wire-meeting-toast-desktop";

const invoke = vi.fn(async (..._args: unknown[]) => undefined);
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
  it("shows the desktop toast with content when a suggestion arrives while idle", () => {
    const unwire = wireMeetingToastDesktop(() => {});
    applyMeetingDetected(meetingDetectionStore, {
      source: "zoom",
      reason: "zoom meeting activity detected",
      confidence: 0.9,
      dedupe_key: "zoom",
    });
    expect(invoke).toHaveBeenCalledWith("set_meeting_toast_visible", {
      visible: true,
      content: {
        suggestion: expect.objectContaining({ source: "zoom", autoStart: false }),
        stopHintReason: null,
      },
    });
    unwire();
  });

  it("always re-invokes set_meeting_toast_visible (no lastVisible cache)", () => {
    const unwire = wireMeetingToastDesktop(() => {});
    applyMeetingDetected(meetingDetectionStore, {
      source: "zoom",
      reason: "zoom meeting activity detected",
      confidence: 0.9,
      dedupe_key: "zoom",
    });
    const afterShow = invoke.mock.calls.length;
    // Same visible=true again (e.g. store notifies without logical change) — still invokes.
    meetingDetectionStore.setState({ ...meetingDetectionStore.getState() });
    expect(invoke.mock.calls.length).toBeGreaterThan(afterShow);
    expect(invoke).toHaveBeenLastCalledWith(
      "set_meeting_toast_visible",
      expect.objectContaining({ visible: true }),
    );
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
    expect(invoke).toHaveBeenCalledWith("set_meeting_toast_visible", {
      visible: false,
      content: null,
    });
    unwire();
  });

  it("Keep going clears stopHintReason on the main store so later hints can show", async () => {
    const handlers = new Map<string, (event: { payload: unknown }) => void>();
    const listen = vi.fn(async (event: string, handler: (e: { payload: unknown }) => void) => {
      handlers.set(event, handler);
      return () => {
        handlers.delete(event);
      };
    });
    transcriptStore.setState({ ...INITIAL_TRANSCRIPT_STATE, captureStatus: "live" }, true);
    const unwire = wireMeetingToastDesktop(() => {}, meetingDetectionStore, transcriptStore, listen);
    applyCaptureSuggestStop(meetingDetectionStore, { reason: "silence for 45s" });
    expect(meetingDetectionStore.getState().stopHintReason).toBe("silence for 45s");
    // Four sequential await listen(...) registrations — flush until keep-going is wired.
    for (let i = 0; i < 8 && !handlers.has(MEETING_TOAST_KEEP_GOING_EVENT); i += 1) {
      await Promise.resolve();
    }
    expect(handlers.has(MEETING_TOAST_KEEP_GOING_EVENT)).toBe(true);
    handlers.get(MEETING_TOAST_KEEP_GOING_EVENT)?.({ payload: null });
    expect(meetingDetectionStore.getState().stopHintReason).toBeNull();
    // A later suggest_stop must be able to show again (main store is clear).
    applyCaptureSuggestStop(meetingDetectionStore, { reason: "call ended" });
    expect(meetingDetectionStore.getState().stopHintReason).toBe("call ended");
    expect(invoke).toHaveBeenCalledWith(
      "set_meeting_toast_visible",
      expect.objectContaining({
        visible: true,
        content: expect.objectContaining({ stopHintReason: "call ended" }),
      }),
    );
    unwire();
    clearStopHint(meetingDetectionStore);
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
