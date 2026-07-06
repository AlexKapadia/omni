/**
 * Detection store tests: fail-closed parsing of meeting.detected /
 * capture.suggest_stop, the dismiss round trip (detection.dismiss with the
 * dedupe key, card cleared even offline), and the capture-started reset.
 */
import { describe, expect, it } from "vitest";
import {
  applyCaptureSuggestStop,
  applyMeetingDetected,
  clearMeetingDetection,
  clearStopHint,
  createMeetingDetectionStore,
  dismissMeetingSuggestion,
  parseMeetingDetectedPayload,
} from "./meeting-detection-store";

const SUGGESTION_PAYLOAD = {
  source: "zoom",
  reason: "zoom meeting activity detected",
  confidence: 0.7,
  dedupe_key: "zoom",
};

describe("parseMeetingDetectedPayload (fail closed)", () => {
  it("accepts the pinned suggestion shape", () => {
    expect(parseMeetingDetectedPayload(SUGGESTION_PAYLOAD)).toEqual({
      source: "zoom",
      reason: "zoom meeting activity detected",
      confidence: 0.7,
      dedupeKey: "zoom",
      autoStart: false,
    });
  });

  it("accepts the auto-start shape (auto_start literal true, no dedupe key)", () => {
    expect(
      parseMeetingDetectedPayload({
        source: "teams",
        reason: "r",
        confidence: 0.9,
        auto_start: true,
      }),
    ).toEqual({ source: "teams", reason: "r", confidence: 0.9, dedupeKey: null, autoStart: true });
  });

  it.each([
    ["not an object", "zoom"],
    ["source missing", { reason: "r", confidence: 0.7 }],
    ["empty source", { ...SUGGESTION_PAYLOAD, source: "" }],
    ["reason missing", { source: "zoom", confidence: 0.7 }],
    ["confidence NaN", { ...SUGGESTION_PAYLOAD, confidence: Number.NaN }],
    ["confidence over 1", { ...SUGGESTION_PAYLOAD, confidence: 1.2 }],
    ["confidence negative", { ...SUGGESTION_PAYLOAD, confidence: -0.1 }],
    ["confidence stringly", { ...SUGGESTION_PAYLOAD, confidence: "0.7" }],
    ["empty dedupe key", { ...SUGGESTION_PAYLOAD, dedupe_key: "" }],
    ["auto_start not literal true", { ...SUGGESTION_PAYLOAD, auto_start: "yes" }],
  ])("rejects %s whole", (_label, payload) => {
    expect(parseMeetingDetectedPayload(payload)).toBeNull();
  });

  it("boundary confidences 0 and 1 are both accepted (engine contract)", () => {
    expect(parseMeetingDetectedPayload({ ...SUGGESTION_PAYLOAD, confidence: 0 })).not.toBeNull();
    expect(parseMeetingDetectedPayload({ ...SUGGESTION_PAYLOAD, confidence: 1 })).not.toBeNull();
  });
});

describe("store transitions", () => {
  it("a malformed event never mutates the store", () => {
    const store = createMeetingDetectionStore();
    applyMeetingDetected(store, { source: "zoom" });
    applyCaptureSuggestStop(store, { reason: 42 });
    expect(store.getState()).toEqual({ suggestion: null, stopHintReason: null });
  });

  it("dismiss sends detection.dismiss with the dedupe key and clears the card", () => {
    const store = createMeetingDetectionStore();
    applyMeetingDetected(store, SUGGESTION_PAYLOAD);
    const sent: Array<[string, Record<string, unknown> | undefined]> = [];
    dismissMeetingSuggestion(store, (name, payload) => {
      sent.push([name, payload]);
      return true;
    });
    expect(sent).toEqual([["detection.dismiss", { dedupe_key: "zoom" }]]);
    expect(store.getState().suggestion).toBeNull();
  });

  it("dismiss clears the card even when the engine is offline (send=false)", () => {
    const store = createMeetingDetectionStore();
    applyMeetingDetected(store, SUGGESTION_PAYLOAD);
    dismissMeetingSuggestion(store, () => false);
    expect(store.getState().suggestion).toBeNull(); // the user's no is honoured
  });

  it("capture started consumes the suggestion and any stop hint", () => {
    const store = createMeetingDetectionStore();
    applyMeetingDetected(store, SUGGESTION_PAYLOAD);
    applyCaptureSuggestStop(store, { reason: "meeting app closed" });
    clearMeetingDetection(store);
    expect(store.getState()).toEqual({ suggestion: null, stopHintReason: null });
  });

  it("keep-going clears only the stop hint, not a pending suggestion", () => {
    const store = createMeetingDetectionStore();
    applyMeetingDetected(store, SUGGESTION_PAYLOAD);
    applyCaptureSuggestStop(store, { reason: "meeting app closed" });
    clearStopHint(store);
    expect(store.getState().stopHintReason).toBeNull();
    expect(store.getState().suggestion).not.toBeNull();
  });
});
