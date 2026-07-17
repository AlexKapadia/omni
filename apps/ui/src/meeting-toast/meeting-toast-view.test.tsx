/**
 * Meeting toast view — Start / Not now invoke desktop shell commands.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { MeetingToastView } from "./meeting-toast-view";
import {
  applyMeetingDetected,
  createMeetingDetectionStore,
  INITIAL_MEETING_DETECTION_STATE,
} from "../lib/meeting-detection-store";

const invoke = vi.fn(async () => undefined);
vi.mock("@tauri-apps/api/core", () => ({
  invoke: (...args: unknown[]) => invoke(...args),
}));

beforeEach(() => {
  invoke.mockClear();
});

afterEach(cleanup);

describe("MeetingToastView", () => {
  it("renders the desktop card and Start invokes meeting_toast_start_capture", () => {
    const store = createMeetingDetectionStore();
    store.setState(INITIAL_MEETING_DETECTION_STATE, true);
    act(() => {
      applyMeetingDetected(store, {
        source: "zoom",
        reason: "zoom meeting activity detected",
        confidence: 0.9,
        dedupe_key: "zoom",
      });
    });
    render(<MeetingToastView store={store} />);
    expect(screen.getByRole("status", { name: "Meeting detected" }).textContent).toContain(
      "Zoom meeting detected",
    );
    fireEvent.click(screen.getByRole("button", { name: "Start capture" }));
    expect(invoke).toHaveBeenCalledWith("meeting_toast_start_capture", {
      title: "Zoom meeting",
    });
  });

  it("Not now invokes meeting_toast_dismiss", () => {
    const store = createMeetingDetectionStore();
    act(() => {
      applyMeetingDetected(store, {
        source: "teams",
        reason: "teams meeting activity detected",
        confidence: 0.8,
        dedupe_key: "teams",
      });
    });
    render(<MeetingToastView store={store} />);
    fireEvent.click(screen.getByRole("button", { name: "Not now" }));
    expect(invoke).toHaveBeenCalledWith("meeting_toast_dismiss");
  });
});
