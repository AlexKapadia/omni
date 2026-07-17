/**
 * Live-screen tests for the reconciliation surfaces: the post-stop
 * "Finalize meeting" flow (verbatim notepad hand-off, honest
 * pending/ready/failed states). Detection toast lives on the App shell —
 * see App__meeting-detected-toast-global and wire-meeting-toast-desktop tests.
 */
import { afterEach, beforeAll, beforeEach, describe, expect, it } from "vitest";
import { act, cleanup, render, screen } from "@testing-library/react";
import { LiveMeetingScreen } from "./live-meeting-screen";
import { engineStatusStore, INITIAL_ENGINE_STATUS } from "../lib/engine-status-store";
import { INITIAL_LIVE_ANSWERS_STATE, liveAnswersStore } from "../lib/live-answers-store";
import {
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
