/**
 * Intelligence frame-listener tests: raw socket frames route to the right
 * stores — answers.hit fills the panel, capture.started clears hits +
 * suggestion + finalize flow (a fresh meeting), meeting.detected /
 * capture.suggest_stop reach the detection store, enhance.* refines a
 * pending finalize, and malformed/unknown/command frames change NOTHING.
 */
import { describe, expect, it } from "vitest";
import { createApprovalCardsStore } from "./approval-cards-store";
import { createIntelligenceFrameListener } from "./live-intelligence-event-wiring";
import { createLiveAnswersStore } from "./live-answers-store";
import { createLiveSummaryStore } from "./live-summary-store";
import { createLiveTranslationStore } from "./live-translation-store";
import { createVaultSuggestionsStore } from "./vault-suggestions-store";
import { createMeetingDetectionStore } from "./meeting-detection-store";
import { createMeetingFinalizeStore } from "./meeting-finalize-store";

function makeAll() {
  const liveAnswers = createLiveAnswersStore();
  const liveSummary = createLiveSummaryStore();
  const liveTranslation = createLiveTranslationStore();
  const vaultSuggestions = createVaultSuggestionsStore();
  const detection = createMeetingDetectionStore();
  const finalize = createMeetingFinalizeStore();
  const approvalCards = createApprovalCardsStore();
  const listener = createIntelligenceFrameListener({
    liveAnswers,
    liveSummary,
    liveTranslation,
    vaultSuggestions,
    detection,
    finalize,
    approvalCards,
  });
  return { liveAnswers, liveSummary, liveTranslation, vaultSuggestions, detection, finalize, approvalCards, listener };
}

function frame(name: string, payload: Record<string, unknown>, kind = "event"): string {
  return JSON.stringify({ v: 1, kind, name, id: "f-1", payload });
}

const HIT_PAYLOAD = {
  question: "what is the Q3 budget?",
  asked_by: "them",
  spotted_to_hit_ms: 640,
  hits: [
    {
      note_path: "Projects/budget.md",
      line_start: 4,
      line_end: 9,
      heading_path: "Q3",
      snippet: "The Q3 budget is 40k.",
      score: 0.031,
    },
  ],
};

describe("createIntelligenceFrameListener", () => {
  it("answers.hit lands in the live answers store", () => {
    const { liveAnswers, listener } = makeAll();
    listener(frame("answers.hit", HIT_PAYLOAD));
    expect(liveAnswers.getState().hits).toHaveLength(1);
    expect(liveAnswers.getState().hits[0]!.question).toBe("what is the Q3 budget?");
  });

  it("capture.started clears hits, the suggestion card, and the finalize flow", () => {
    const { liveAnswers, detection, finalize, listener } = makeAll();
    listener(frame("answers.hit", HIT_PAYLOAD));
    listener(
      frame("meeting.detected", {
        source: "zoom",
        reason: "zoom meeting activity detected",
        confidence: 0.7,
        dedupe_key: "zoom",
      }),
    );
    finalize.setState({ status: "ready", meetingId: "old", notePath: "Meetings/old.md" });
    listener(frame("capture.started", { meeting_id: "m-2", reason: "command" }));
    expect(liveAnswers.getState().hits).toEqual([]); // hits belong to one meeting
    expect(detection.getState().suggestion).toBeNull(); // card consumed
    expect(finalize.getState().status).toBe("idle"); // previous flow is over
  });

  it("meeting.detected and capture.suggest_stop reach the detection store", () => {
    const { detection, listener } = makeAll();
    listener(
      frame("meeting.detected", {
        source: "browser_meet",
        reason: "browser_meet meeting activity detected",
        confidence: 0.85,
        dedupe_key: "browser_meet",
      }),
    );
    listener(frame("capture.suggest_stop", { reason: "meeting app closed" }));
    expect(detection.getState().suggestion?.source).toBe("browser_meet");
    expect(detection.getState().stopHintReason).toBe("meeting app closed");
  });

  it("enhance.ready and enhance.failed refine a pending finalize", () => {
    const { finalize, listener } = makeAll();
    finalize.setState({ status: "pending", meetingId: "m-1" });
    listener(frame("enhance.ready", { meeting_id: "m-1", note_path: "Meetings/x.md" }));
    expect(finalize.getState().status).toBe("ready");
    finalize.setState({ status: "pending", meetingId: "m-2", notePath: null });
    listener(frame("enhance.failed", { meeting_id: "m-2", reason: "no keys" }));
    expect(finalize.getState().status).toBe("failed");
  });

  it("card.updated events and cards.list ok-replies reach the approval store", () => {
    const { approvalCards, listener } = makeAll();
    const card = {
      id: 7,
      meeting_id: "m-1",
      source: "extraction",
      card_type: "create_event",
      status: "pending",
      payload: { title: "Sync" },
      preview_lines: ["Event: Sync"],
      created_at: "2026-07-06T12:00:00+00:00",
      decided_at: null,
      executed_at: null,
      error: null,
      result_summary: null,
    };
    // The cards.list reply is an `ok` reply carrying a `cards` array.
    listener(frame("ok", { cards: [card] }, "reply"));
    expect(approvalCards.getState().loaded).toBe(true);
    expect(approvalCards.getState().cards).toHaveLength(1);
    // A status change arrives exclusively via card.updated (optimistic-free).
    listener(frame("card.updated", { card: { ...card, status: "approved" } }));
    expect(approvalCards.getState().cards[0]!.status).toBe("approved");
    // Other ok replies (no cards array) change nothing.
    listener(frame("ok", { meetings: [] }, "reply"));
    expect(approvalCards.getState().cards).toHaveLength(1);
  });

  it("malformed frames, commands, and unknown events change NOTHING", () => {
    const { liveAnswers, detection, finalize, listener } = makeAll();
    listener("not json at all");
    listener(frame("answers.hit", HIT_PAYLOAD, "command")); // inbound commands rejected
    listener(frame("answers.hit", { question: "" })); // malformed payload
    listener(frame("meeting.detected", { source: "zoom" })); // malformed payload
    listener(frame("totally.unknown", { anything: 1 })); // deny by default
    listener(JSON.stringify({ v: 2, kind: "event", name: "answers.hit", id: "x", payload: {} }));
    expect(liveAnswers.getState().hits).toEqual([]);
    expect(detection.getState().suggestion).toBeNull();
    expect(finalize.getState().status).toBe("idle");
  });
});
