/**
 * Fail-closed proof for the Naomi turn-loop parsers: every inbound turn event
 * is untrusted input, so each parser must accept ONLY the exact frozen shape
 * and reject every deviation (null), with the one deliberate exception that a
 * malformed/out-of-range reply affect is DROPPED (affect→null) while the reply
 * itself is still delivered. Mirrors naomi-voice-protocol's test style.
 */
import { describe, expect, it } from "vitest";
import {
  buildNaomiListenStartPayload,
  buildNaomiListenStopPayload,
  parseNaomiReplyPayload,
  parseNaomiStatePayload,
  parseNaomiTurnErrorPayload,
  parseNaomiTurnLatencyPayload,
  parseNaomiUserUtterancePayload,
} from "./naomi-turn-protocol";

const rec = (o: Record<string, unknown>) => o;

describe("command builders mirror the engine pydantic defaults", () => {
  it("listen.start carries open_mic", () => {
    expect(buildNaomiListenStartPayload(true)).toEqual({ open_mic: true });
    expect(buildNaomiListenStartPayload(false)).toEqual({ open_mic: false });
  });
  it("listen.stop carries flush", () => {
    expect(buildNaomiListenStopPayload(true)).toEqual({ flush: true });
    expect(buildNaomiListenStopPayload(false)).toEqual({ flush: false });
  });
});

describe("naomi.state", () => {
  it.each(["idle", "listening", "thinking", "speaking"] as const)("accepts %s", (state) => {
    expect(parseNaomiStatePayload({ state })).toEqual({ state, turn_id: null });
  });
  it("keeps a valid turn_id", () => {
    expect(parseNaomiStatePayload({ state: "thinking", turn_id: "t-9" })?.turn_id).toBe("t-9");
  });
  it.each([
    ["unknown state string", { state: "dreaming" }],
    ["numeric state", { state: 2 }],
    ["missing state", {}],
    ["empty turn_id", { state: "idle", turn_id: "" }],
    ["numeric turn_id", { state: "idle", turn_id: 7 }],
  ])("rejects %s", (_n, payload) => {
    expect(parseNaomiStatePayload(rec(payload))).toBeNull();
  });
});

describe("naomi.user_utterance (verbatim)", () => {
  it("accepts and preserves text exactly", () => {
    const p = { turn_id: "t1", text: "um, what did i say about the Q3 plan?" };
    expect(parseNaomiUserUtterancePayload(p)).toEqual(p);
  });
  it.each([
    ["missing turn_id", { text: "hi" }],
    ["empty turn_id", { turn_id: "", text: "hi" }],
    ["missing text", { turn_id: "t1" }],
    ["empty text", { turn_id: "t1", text: "" }],
    ["numeric text", { turn_id: "t1", text: 42 }],
  ])("rejects %s", (_n, payload) => {
    expect(parseNaomiUserUtterancePayload(rec(payload))).toBeNull();
  });
});

const CITATION = {
  n: 1,
  note_path: "Notes/Meetings/2026-07-06 Sync.md",
  line_start: 12,
  line_end: 14,
  heading_path: "Sync > Decisions",
  quote: "We agreed to ship on Friday.",
};

const REPLY = {
  turn_id: "t1",
  text: "You agreed to ship on Friday. [1]",
  no_answer: false,
  citations: [CITATION],
  affect: { v: 0.4, a: 0.5, burst: "laugh" },
  action_card_id: 7,
};

describe("naomi.reply", () => {
  it("accepts the full shape (affect + citations + card)", () => {
    const parsed = parseNaomiReplyPayload({ ...REPLY });
    expect(parsed).not.toBeNull();
    expect(parsed?.affect).toEqual({ v: 0.4, a: 0.5, burst: "laugh" });
    expect(parsed?.citations).toEqual([CITATION]);
    expect(parsed?.action_card_id).toBe(7);
    expect(parsed?.no_answer).toBe(false);
  });

  it("accepts a no-answer reply with empty citations and no card", () => {
    const parsed = parseNaomiReplyPayload({
      turn_id: "t1",
      text: "I couldn't find that in your notes.",
      no_answer: true,
      citations: [],
    });
    expect(parsed?.no_answer).toBe(true);
    expect(parsed?.affect).toBeNull();
    expect(parsed?.action_card_id).toBeNull();
  });

  it("treats heading_path='' and quote='' as valid (root-level provenance)", () => {
    const parsed = parseNaomiReplyPayload({
      ...REPLY,
      citations: [{ ...CITATION, heading_path: "", quote: "" }],
    });
    expect(parsed).not.toBeNull();
  });

  it.each([
    ["missing turn_id", { ...REPLY, turn_id: undefined }],
    ["empty text", { ...REPLY, text: "" }],
    ["non-boolean no_answer", { ...REPLY, no_answer: "false" }],
    ["missing no_answer", { ...REPLY, no_answer: undefined }],
    ["citations not an array", { ...REPLY, citations: {} }],
    ["fractional action_card_id", { ...REPLY, action_card_id: 1.5 }],
    ["zero action_card_id", { ...REPLY, action_card_id: 0 }],
  ])("rejects the whole reply on %s", (_n, payload) => {
    expect(parseNaomiReplyPayload(rec(payload))).toBeNull();
  });

  it.each([
    ["non-integer n", { ...CITATION, n: 1.5 }],
    ["zero n", { ...CITATION, n: 0 }],
    ["empty note_path", { ...CITATION, note_path: "" }],
    ["fractional line_start", { ...CITATION, line_start: 12.5 }],
    ["zero line_end", { ...CITATION, line_end: 0 }],
    ["numeric heading_path", { ...CITATION, heading_path: 3 }],
    ["numeric quote", { ...CITATION, quote: 9 }],
    ["citation not an object", "nope"],
  ])("rejects the whole reply when a citation member is malformed: %s", (_n, badCitation) => {
    expect(parseNaomiReplyPayload({ ...REPLY, citations: [badCitation] })).toBeNull();
  });

  it.each([
    ["valence over range", { v: 1.5, a: 0.5 }],
    ["valence under range", { v: -1.5, a: 0.5 }],
    ["arousal over range", { v: 0, a: 1.5 }],
    ["arousal negative", { v: 0, a: -0.1 }],
    ["unknown burst", { v: 0, a: 0.5, burst: "cough" }],
    ["non-numeric v", { v: "x", a: 0.5 }],
    ["affect not an object", "loud"],
  ])("DROPS affect to null but keeps the reply: %s", (_n, badAffect) => {
    const parsed = parseNaomiReplyPayload({ ...REPLY, affect: badAffect });
    expect(parsed).not.toBeNull();
    expect(parsed?.affect).toBeNull();
    expect(parsed?.text).toBe(REPLY.text); // the reply body survives
  });

  it("keeps in-range affect at the exact boundaries", () => {
    const parsed = parseNaomiReplyPayload({ ...REPLY, affect: { v: -1, a: 0 } });
    expect(parsed?.affect).toEqual({ v: -1, a: 0, burst: null });
  });
});

const LATENCY = {
  turn_id: "t1",
  endpoint_ms: 120,
  retrieval_ms: 40,
  llm_ms: 300,
  ttfa_ms: 220,
  total_ms: 460,
};

describe("naomi.turn.latency (integers only)", () => {
  it("accepts non-negative integer spans", () => {
    expect(parseNaomiTurnLatencyPayload({ ...LATENCY })).toEqual(LATENCY);
  });
  it("accepts zero spans (a cache-hit turn)", () => {
    const zeroed = { ...LATENCY, retrieval_ms: 0, llm_ms: 0 };
    expect(parseNaomiTurnLatencyPayload(zeroed)).toEqual(zeroed);
  });
  it.each([
    ["fractional ms", { ...LATENCY, llm_ms: 300.5 }],
    ["negative ms", { ...LATENCY, endpoint_ms: -1 }],
    ["string ms", { ...LATENCY, total_ms: "460" }],
    ["NaN ms", { ...LATENCY, ttfa_ms: Number.NaN }],
    ["missing field", { ...LATENCY, retrieval_ms: undefined }],
    ["missing turn_id", { ...LATENCY, turn_id: undefined }],
  ])("rejects %s", (_n, payload) => {
    expect(parseNaomiTurnLatencyPayload(rec(payload))).toBeNull();
  });
});

describe("naomi.turn.error", () => {
  it("accepts a bounded message with optional turn_id", () => {
    expect(parseNaomiTurnErrorPayload({ message: "provider timed out" })).toEqual({
      message: "provider timed out",
      turn_id: null,
    });
    expect(parseNaomiTurnErrorPayload({ message: "x", turn_id: "t1" })?.turn_id).toBe("t1");
  });
  it.each([
    ["empty message", { message: "" }],
    ["missing message", {}],
    ["numeric message", { message: 500 }],
    ["oversized message", { message: "x".repeat(2001) }],
    ["empty turn_id", { message: "x", turn_id: "" }],
  ])("rejects %s", (_n, payload) => {
    expect(parseNaomiTurnErrorPayload(rec(payload))).toBeNull();
  });
});
