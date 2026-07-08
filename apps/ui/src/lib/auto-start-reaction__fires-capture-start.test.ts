import { describe, expect, it, vi } from "vitest";
import { maybeAutoStartCaptureOnDetection } from "./auto-start-reaction";
import type { MeetingSuggestion } from "./meeting-detection-store";
import { createTranscriptStore } from "./transcript-store";

const AUTO_START: MeetingSuggestion = {
  source: "zoom",
  reason: "zoom meeting detected (user-enabled auto-start)",
  confidence: 0.9,
  dedupeKey: null,
  autoStart: true,
};

const SUGGEST_ONLY: MeetingSuggestion = {
  ...AUTO_START,
  autoStart: false,
  dedupeKey: "zoom",
};

describe("maybeAutoStartCaptureOnDetection", () => {
  it("fires capture.start when autoStart is true and capture is idle", () => {
    const store = createTranscriptStore();
    const start = vi.fn(() => true);
    maybeAutoStartCaptureOnDetection(AUTO_START, store, start);
    expect(start).toHaveBeenCalledExactlyOnceWith("zoom");
  });

  it("fires when capture previously stopped", () => {
    const store = createTranscriptStore();
    store.setState({ captureStatus: "stopped" });
    const start = vi.fn(() => true);
    maybeAutoStartCaptureOnDetection(AUTO_START, store, start);
    expect(start).toHaveBeenCalledOnce();
  });

  it("does nothing for suggestion-only cards", () => {
    const store = createTranscriptStore();
    const start = vi.fn(() => true);
    maybeAutoStartCaptureOnDetection(SUGGEST_ONLY, store, start);
    expect(start).not.toHaveBeenCalled();
  });

  it("does nothing while capture is already live or in-flight", () => {
    const start = vi.fn(() => true);
    for (const captureStatus of ["live", "starting", "stopping"] as const) {
      const store = createTranscriptStore();
      store.setState({ captureStatus });
      maybeAutoStartCaptureOnDetection(AUTO_START, store, start);
    }
    expect(start).not.toHaveBeenCalled();
  });
});
