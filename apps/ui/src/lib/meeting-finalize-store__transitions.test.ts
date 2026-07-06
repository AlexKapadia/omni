/**
 * Finalize-store tests: the honest idle -> pending -> ready | failed flow,
 * verbatim notepad hand-off, enhance.* event refinement gated by meeting id
 * and pending status, double-submit protection, and the capture reset.
 */
import { describe, expect, it } from "vitest";
import type { FinalizeOutcome } from "./meetings-live-repository";
import {
  applyEnhanceFailed,
  applyEnhanceReady,
  createMeetingFinalizeStore,
  finalizeMeeting,
  resetMeetingFinalize,
} from "./meeting-finalize-store";

const OUTCOME: FinalizeOutcome = {
  notePath: "Meetings/2026-07-06 Vendor sync.md",
  enhanceOk: true,
  extractionOk: true,
  warnings: ["indexing unavailable: vec model missing"],
};

describe("finalizeMeeting", () => {
  it("passes the notepad buffer verbatim and lands ready with the real path", async () => {
    const store = createMeetingFinalizeStore();
    const calls: Array<[string, string]> = [];
    await finalizeMeeting("m-1", "  my rough notes\n\twith exact bytes  ", store, async (id, text) => {
      calls.push([id, text]);
      return OUTCOME;
    });
    expect(calls).toEqual([["m-1", "  my rough notes\n\twith exact bytes  "]]);
    const state = store.getState();
    expect(state.status).toBe("ready");
    expect(state.notePath).toBe("Meetings/2026-07-06 Vendor sync.md");
    expect(state.warnings).toEqual(["indexing unavailable: vec model missing"]);
    expect(state.errorMessage).toBeNull();
  });

  it("is pending while the request runs and refuses a second submit", async () => {
    const store = createMeetingFinalizeStore();
    let resolveRequest: (outcome: FinalizeOutcome) => void = () => undefined;
    const first = finalizeMeeting(
      "m-1",
      "notes",
      store,
      () => new Promise<FinalizeOutcome>((resolve) => (resolveRequest = resolve)),
    );
    expect(store.getState().status).toBe("pending");
    // Double-submit protection: a second call while pending does nothing.
    await finalizeMeeting("m-1", "notes", store, async () => {
      throw new Error("must not be called");
    });
    resolveRequest(OUTCOME);
    await first;
    expect(store.getState().status).toBe("ready");
  });

  it("a refusal lands failed with the engine's own message", async () => {
    const store = createMeetingFinalizeStore();
    await finalizeMeeting("m-1", "notes", store, async () => {
      throw new Error("meeting is already finalized");
    });
    const state = store.getState();
    expect(state.status).toBe("failed");
    expect(state.errorMessage).toBe("meeting is already finalized");
    expect(state.notePath).toBeNull(); // no fake success artifacts
  });
});

describe("enhance.* event refinement", () => {
  it("enhance.ready for the pending meeting flips to ready with the path", () => {
    const store = createMeetingFinalizeStore();
    store.setState({ status: "pending", meetingId: "m-1" });
    applyEnhanceReady(store, { meeting_id: "m-1", note_path: "Meetings/x.md" });
    expect(store.getState().status).toBe("ready");
    expect(store.getState().notePath).toBe("Meetings/x.md");
  });

  it("enhance events for a DIFFERENT meeting never mutate the flow", () => {
    const store = createMeetingFinalizeStore();
    store.setState({ status: "pending", meetingId: "m-1" });
    applyEnhanceReady(store, { meeting_id: "m-OTHER", note_path: "Meetings/x.md" });
    applyEnhanceFailed(store, { meeting_id: "m-OTHER", reason: "boom" });
    expect(store.getState().status).toBe("pending"); // stale-event defence
  });

  it("enhance.failed while pending surfaces the honest reason", () => {
    const store = createMeetingFinalizeStore();
    store.setState({ status: "pending", meetingId: "m-1" });
    applyEnhanceFailed(store, { meeting_id: "m-1", reason: "no provider keys configured" });
    expect(store.getState().status).toBe("failed");
    expect(store.getState().errorMessage).toBe("no provider keys configured");
  });

  it("malformed enhance payloads are dropped whole (fail closed)", () => {
    const store = createMeetingFinalizeStore();
    store.setState({ status: "pending", meetingId: "m-1" });
    applyEnhanceReady(store, { meeting_id: "m-1" }); // note_path missing
    applyEnhanceReady(store, { meeting_id: "m-1", note_path: "" });
    applyEnhanceFailed(store, { meeting_id: "m-1", reason: "" });
    applyEnhanceFailed(store, "not an object");
    expect(store.getState().status).toBe("pending");
  });

  it("events after settlement do not regress a ready flow", () => {
    const store = createMeetingFinalizeStore();
    store.setState({ status: "ready", meetingId: "m-1", notePath: "Meetings/x.md" });
    applyEnhanceFailed(store, { meeting_id: "m-1", reason: "late failure" });
    expect(store.getState().status).toBe("ready"); // only pending refines
  });
});

describe("reset", () => {
  it("a new capture resets the flow to idle", () => {
    const store = createMeetingFinalizeStore();
    store.setState({ status: "ready", meetingId: "m-1", notePath: "Meetings/x.md" });
    resetMeetingFinalize(store);
    expect(store.getState()).toEqual({
      status: "idle",
      meetingId: null,
      notePath: null,
      errorMessage: null,
      warnings: [],
    });
  });
});
