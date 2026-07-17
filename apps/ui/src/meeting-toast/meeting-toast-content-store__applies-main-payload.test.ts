/**
 * Overlay content store: main-window payloads are the single source of truth.
 */
import { describe, expect, it } from "vitest";
import {
  applyMeetingToastContent,
  meetingToastContentStore,
} from "./meeting-toast-content-store";
import {
  createMeetingDetectionStore,
  INITIAL_MEETING_DETECTION_STATE,
} from "../lib/meeting-detection-store";

describe("applyMeetingToastContent", () => {
  it("applies a suggestion payload from the main window", () => {
    const store = createMeetingDetectionStore();
    applyMeetingToastContent(store, {
      suggestion: {
        source: "zoom",
        reason: "zoom meeting activity detected",
        confidence: 0.9,
        dedupeKey: "zoom",
        autoStart: false,
      },
      stopHintReason: null,
    });
    expect(store.getState().suggestion?.source).toBe("zoom");
    expect(store.getState().stopHintReason).toBeNull();
  });

  it("applies a stop-hint payload", () => {
    const store = createMeetingDetectionStore();
    applyMeetingToastContent(store, {
      suggestion: null,
      stopHintReason: "silence for 45s",
    });
    expect(store.getState().suggestion).toBeNull();
    expect(store.getState().stopHintReason).toBe("silence for 45s");
  });

  it("clears on null / empty content", () => {
    meetingToastContentStore.setState({
      suggestion: {
        source: "zoom",
        reason: "r",
        confidence: 1,
        dedupeKey: "z",
        autoStart: false,
      },
      stopHintReason: "old",
    });
    applyMeetingToastContent(meetingToastContentStore, null);
    expect(meetingToastContentStore.getState()).toEqual(INITIAL_MEETING_DETECTION_STATE);
  });
});
