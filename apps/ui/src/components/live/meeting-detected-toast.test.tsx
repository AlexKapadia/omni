/**
 * MeetingDetectedToast — suggestion + stop-hint behaviours (unit surface).
 * App-level global mount is covered by App__meeting-detected-toast-global.
 */
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { MeetingDetectedToast } from "./meeting-detected-toast";
import {
  applyCaptureSuggestStop,
  applyMeetingDetected,
  INITIAL_MEETING_DETECTION_STATE,
  meetingDetectionStore,
} from "../../lib/meeting-detection-store";
import { INITIAL_TRANSCRIPT_STATE, transcriptStore } from "../../lib/transcript-store";
import { installJsdomMatchMediaShim } from "../../test-support/install-jsdom-match-media-shim";

beforeAll(installJsdomMatchMediaShim);

beforeEach(() => {
  meetingDetectionStore.setState(INITIAL_MEETING_DETECTION_STATE, true);
  transcriptStore.setState(INITIAL_TRANSCRIPT_STATE, true);
});

afterEach(cleanup);

const SUGGESTION = {
  source: "zoom",
  reason: "zoom meeting activity detected",
  confidence: 0.7,
  dedupe_key: "zoom",
};

describe("MeetingDetectedToast", () => {
  it("raises Start capturing? while idle", () => {
    act(() => {
      applyMeetingDetected(meetingDetectionStore, SUGGESTION);
    });
    render(<MeetingDetectedToast />);
    const toast = screen.getByRole("status", { name: "Meeting detected" });
    expect(toast.textContent).toContain("Zoom meeting detected");
    expect(toast.textContent).toContain("Capture on this device");
    act(() => {
      fireEvent.click(within(toast).getByRole("button", { name: "Start capture" }));
    });
    // No socket in jsdom — capture command fails closed with an honest error.
    expect(transcriptStore.getState().errorMessage).not.toBeNull();
  });

  it("calls onStartCapture when provided instead of bare capture.start", () => {
    const onStart = vi.fn();
    act(() => {
      applyMeetingDetected(meetingDetectionStore, SUGGESTION);
    });
    render(<MeetingDetectedToast onStartCapture={onStart} />);
    act(() => {
      fireEvent.click(screen.getByRole("button", { name: "Start capture" }));
    });
    expect(onStart).toHaveBeenCalledTimes(1);
  });

  it("Not now clears the card", () => {
    act(() => {
      applyMeetingDetected(meetingDetectionStore, SUGGESTION);
    });
    render(<MeetingDetectedToast />);
    act(() => {
      fireEvent.click(screen.getByRole("button", { name: "Not now" }));
    });
    expect(meetingDetectionStore.getState().suggestion).toBeNull();
    expect(screen.queryByRole("status", { name: "Meeting detected" })).toBeNull();
  });

  it("capture.suggest_stop shows ONLY while live; Keep going clears it", () => {
    act(() => {
      applyCaptureSuggestStop(meetingDetectionStore, { reason: "meeting app closed" });
    });
    const { rerender } = render(<MeetingDetectedToast />);
    expect(screen.queryByRole("status", { name: "Capture stop suggested" })).toBeNull();
    act(() => {
      transcriptStore.setState({
        captureStatus: "live",
        meetingId: "m1",
        captureStartedAtMs: Date.now(),
      });
    });
    rerender(<MeetingDetectedToast />);
    const hint = screen.getByRole("status", { name: "Capture stop suggested" });
    expect(hint.textContent).toContain("meeting app closed — stop capturing?");
    act(() => {
      fireEvent.click(screen.getByRole("button", { name: "Keep going" }));
    });
    expect(meetingDetectionStore.getState().stopHintReason).toBeNull();
    expect(screen.queryByRole("status", { name: "Capture stop suggested" })).toBeNull();
  });
});
