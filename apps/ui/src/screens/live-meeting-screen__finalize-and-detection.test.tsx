/**
 * Live-screen tests for the reconciliation surfaces: the post-stop
 * "Finalize meeting" flow (verbatim notepad hand-off, honest
 * pending/ready/failed states) and the detection toast ("Start capturing?"
 * one-click + dismiss, the stop hint while live).
 */
import { afterEach, beforeAll, beforeEach, describe, expect, it } from "vitest";
import { act, cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { LiveMeetingScreen } from "./live-meeting-screen";
import { engineStatusStore, INITIAL_ENGINE_STATUS } from "../lib/engine-status-store";
import { INITIAL_LIVE_ANSWERS_STATE, liveAnswersStore } from "../lib/live-answers-store";
import {
  applyCaptureSuggestStop,
  applyMeetingDetected,
  INITIAL_MEETING_DETECTION_STATE,
  meetingDetectionStore,
} from "../lib/meeting-detection-store";
import {
  applyEnhanceFailed,
  applyEnhanceReady,
  INITIAL_MEETING_FINALIZE_STATE,
  meetingFinalizeStore,
} from "../lib/meeting-finalize-store";
import { INITIAL_NOTEPAD_STATE, notepadStore } from "../lib/notepad-store";
import { INITIAL_TRANSCRIPT_STATE, transcriptStore } from "../lib/transcript-store";
import { installJsdomMatchMediaShim } from "../test-support/install-jsdom-match-media-shim";

beforeAll(installJsdomMatchMediaShim);

beforeEach(() => {
  transcriptStore.setState(INITIAL_TRANSCRIPT_STATE, true);
  engineStatusStore.setState(INITIAL_ENGINE_STATUS, true);
  notepadStore.setState(INITIAL_NOTEPAD_STATE, true);
  liveAnswersStore.setState(INITIAL_LIVE_ANSWERS_STATE, true);
  meetingDetectionStore.setState(INITIAL_MEETING_DETECTION_STATE, true);
  meetingFinalizeStore.setState(INITIAL_MEETING_FINALIZE_STATE, true);
});

afterEach(cleanup);

const SUGGESTION = {
  source: "zoom",
  reason: "zoom meeting activity detected",
  confidence: 0.7,
  dedupe_key: "zoom",
};

describe("finalize flow (stopped state)", () => {
  it("offers Finalize meeting after a stop, and pending disables it honestly", () => {
    transcriptStore.setState({ captureStatus: "stopped", meetingId: "m1" });
    render(<LiveMeetingScreen />);
    const finalize = screen.getByRole("button", { name: "Finalize meeting" });
    expect((finalize as HTMLButtonElement).disabled).toBe(false);
    act(() => {
      meetingFinalizeStore.setState({ status: "pending", meetingId: "m1" });
    });
    const pending = screen.getByRole("button", { name: "Enhancing notes" });
    expect((pending as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getByText(/Fusing your notes with the transcript/)).toBeTruthy();
  });

  it("ready shows the REAL note path (and honest warnings), no button left", () => {
    transcriptStore.setState({ captureStatus: "stopped", meetingId: "m1" });
    render(<LiveMeetingScreen />);
    act(() => {
      meetingFinalizeStore.setState({ status: "pending", meetingId: "m1" });
      applyEnhanceReady(meetingFinalizeStore, {
        meeting_id: "m1",
        note_path: "Meetings/2026-07-06 Vendor sync.md",
      });
      meetingFinalizeStore.setState({ warnings: ["indexing unavailable: vec model missing"] });
    });
    expect(screen.getByText(/Enhanced note saved to/)).toBeTruthy();
    expect(screen.getByText("Meetings/2026-07-06 Vendor sync.md")).toBeTruthy();
    expect(screen.getByText("indexing unavailable: vec model missing")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Finalize meeting" })).toBeNull();
  });

  it("failed keeps the engine's own reason visible and offers a retry", () => {
    transcriptStore.setState({ captureStatus: "stopped", meetingId: "m1" });
    render(<LiveMeetingScreen />);
    act(() => {
      meetingFinalizeStore.setState({ status: "pending", meetingId: "m1" });
      applyEnhanceFailed(meetingFinalizeStore, {
        meeting_id: "m1",
        reason: "no provider keys configured",
      });
    });
    expect(screen.getByRole("alert").textContent).toBe("no provider keys configured");
    expect(screen.getByRole("button", { name: "Retry finalize" })).toBeTruthy();
  });

  it("no finalize surface without a meeting (idle screen)", () => {
    render(<LiveMeetingScreen />);
    expect(screen.queryByRole("button", { name: "Finalize meeting" })).toBeNull();
  });
});

describe("detection toast", () => {
  it("meeting.detected raises the one-click Start capturing? card while idle", () => {
    engineStatusStore.setState({ status: "connected" });
    act(() => {
      applyMeetingDetected(meetingDetectionStore, SUGGESTION);
    });
    render(<LiveMeetingScreen />);
    const toast = screen.getByRole("status", { name: "Meeting detected" });
    expect(toast.textContent).toContain("zoom meeting activity detected — start capturing?");
    // One click sends the ordinary capture.start; no socket in jsdom means
    // the command layer refuses honestly — the toast's action is REAL.
    act(() => {
      fireEvent.click(within(toast).getByRole("button", { name: "Start capture" }));
    });
    expect(transcriptStore.getState().errorMessage).not.toBeNull(); // fail closed
  });

  it("Dismiss clears the card (and the engine cooldown ride-along is best-effort)", () => {
    act(() => {
      applyMeetingDetected(meetingDetectionStore, SUGGESTION);
    });
    render(<LiveMeetingScreen />);
    act(() => {
      fireEvent.click(screen.getByRole("button", { name: "Dismiss" }));
    });
    expect(meetingDetectionStore.getState().suggestion).toBeNull();
    expect(screen.queryByRole("status", { name: "Meeting detected" })).toBeNull();
  });

  it("capture.suggest_stop shows the stop hint ONLY while live, and Keep going clears it", () => {
    act(() => {
      applyCaptureSuggestStop(meetingDetectionStore, { reason: "meeting app closed" });
    });
    render(<LiveMeetingScreen />); // idle: no hint surface at all
    expect(screen.queryByRole("status", { name: "Capture stop suggested" })).toBeNull();
    act(() => {
      transcriptStore.setState({
        captureStatus: "live",
        meetingId: "m1",
        captureStartedAtMs: Date.now(),
      });
    });
    const hint = screen.getByRole("status", { name: "Capture stop suggested" });
    expect(hint.textContent).toContain("meeting app closed — stop capturing?");
    act(() => {
      fireEvent.click(screen.getByRole("button", { name: "Keep going" }));
    });
    expect(meetingDetectionStore.getState().stopHintReason).toBeNull();
    expect(screen.queryByRole("status", { name: "Capture stop suggested" })).toBeNull();
  });
});
