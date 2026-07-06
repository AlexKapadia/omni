/**
 * Dictation payload parsers are fail-closed: every deviation from the
 * pinned shapes returns null — a half-valid final could send the user to a
 * note that does not exist, so partial acceptance is forbidden.
 */
import { describe, expect, it } from "vitest";

import {
  parseDictationErrorPayload,
  parseDictationFinalPayload,
  parseDictationPartialPayload,
} from "./dictation-events-protocol";

describe("dictation.partial", () => {
  it("accepts verbatim text, including the empty string (silence)", () => {
    expect(parseDictationPartialPayload({ text: "buy milk" })).toEqual({ text: "buy milk" });
    expect(parseDictationPartialPayload({ text: "" })).toEqual({ text: "" });
  });

  it.each([[{}], [{ text: 7 }], [{ text: null }], [{ text: ["x"] }]])(
    "rejects %j",
    (payload) => {
      expect(parseDictationPartialPayload(payload as Record<string, unknown>)).toBeNull();
    },
  );
});

describe("dictation.final", () => {
  const validNote = {
    mode: "note",
    text: "buy milk",
    note_path: "C:/vault/Inbox/Buy milk.md",
    note_title: "Buy milk",
    title_source: "model",
  };
  const validCommand = {
    mode: "command",
    text: "Omni, schedule lunch",
    intent: {
      intent_type: "create_event",
      fields: { title: "lunch" },
      confidence: 0.9,
    },
  };

  it("accepts a full note final", () => {
    expect(parseDictationFinalPayload(validNote)).toEqual(validNote);
  });

  it("accepts a full command final", () => {
    expect(parseDictationFinalPayload(validCommand)).toEqual(validCommand);
  });

  it("accepts the minimal shape (mode + text only)", () => {
    expect(parseDictationFinalPayload({ mode: "note", text: "" })).toEqual({
      mode: "note",
      text: "",
    });
  });

  const validInject = {
    mode: "inject",
    text: "um send the report",
    cleaned_text: "Send the report.",
    cleanup_source: "model",
    cleanup_latency_ms: 412,
    flush_ms: 96,
  };

  it("accepts a full inject final (cleanup + speed fields)", () => {
    expect(parseDictationFinalPayload(validInject)).toEqual(validInject);
  });

  it("accepts a note final carrying cleanup fields", () => {
    const noteWithCleanup = {
      ...validNote,
      cleaned_text: "Buy milk.",
      cleanup_source: "model",
      cleanup_latency_ms: 300,
    };
    expect(parseDictationFinalPayload(noteWithCleanup)).toEqual(noteWithCleanup);
  });

  it("accepts latency stamps of exactly 0 ms (boundary)", () => {
    const parsed = parseDictationFinalPayload({ ...validInject, cleanup_latency_ms: 0 });
    expect(parsed?.cleanup_latency_ms).toBe(0);
  });

  it.each([
    [{ ...validInject, cleaned_text: "" }], // present-but-empty
    [{ ...validInject, cleaned_text: 7 }],
    [{ ...validInject, cleanup_source: 1 }],
    [{ ...validInject, cleanup_latency_ms: "412" }], // stringly-typed number
    [{ ...validInject, cleanup_latency_ms: -1 }], // negative latency is a lie
    [{ ...validInject, cleanup_latency_ms: Number.NaN }],
    [{ ...validInject, flush_ms: Number.POSITIVE_INFINITY }],
  ])("rejects malformed cleanup/speed fields %j", (payload) => {
    expect(parseDictationFinalPayload(payload as Record<string, unknown>)).toBeNull();
  });

  it("keeps degraded_reason when present (honest partial failure)", () => {
    const parsed = parseDictationFinalPayload({
      mode: "note",
      text: "x",
      degraded_reason: "indexing failed: sqlite-vec missing",
    });
    expect(parsed?.degraded_reason).toBe("indexing failed: sqlite-vec missing");
  });

  it.each([
    [{}],
    [{ mode: "note" }], // text missing
    [{ mode: "shout", text: "x" }], // unknown mode
    [{ mode: "note", text: 7 }],
    [{ ...validNote, note_path: "" }], // present-but-empty optional
    [{ ...validNote, note_title: 3 }],
    [{ ...validCommand, intent: { intent_type: "create_event" } }], // intent missing keys
    [{ ...validCommand, intent: { intent_type: "rm_rf", fields: {}, confidence: 1 } }],
    [{ ...validCommand, intent: { intent_type: "create_event", fields: [], confidence: 1 } }],
    [
      {
        ...validCommand,
        intent: { intent_type: "create_event", fields: {}, confidence: 1.01 },
      },
    ], // just over the confidence ceiling
    [
      {
        ...validCommand,
        intent: { intent_type: "create_event", fields: {}, confidence: -0.01 },
      },
    ],
    [
      {
        ...validCommand,
        intent: { intent_type: "create_event", fields: {}, confidence: Number.NaN },
      },
    ],
  ])("rejects %j", (payload) => {
    expect(parseDictationFinalPayload(payload as Record<string, unknown>)).toBeNull();
  });

  it("confidence boundaries 0 and 1 are inclusive", () => {
    for (const confidence of [0, 1]) {
      const parsed = parseDictationFinalPayload({
        ...validCommand,
        intent: { intent_type: "create_event", fields: {}, confidence },
      });
      expect(parsed?.intent?.confidence).toBe(confidence);
    }
  });
});

describe("dictation.error", () => {
  it("accepts a non-empty reason", () => {
    expect(parseDictationErrorPayload({ reason: "mic missing" })).toEqual({
      reason: "mic missing",
    });
  });

  it.each([[{}], [{ reason: "" }], [{ reason: 1 }], [{ reason: null }]])(
    "rejects %j",
    (payload) => {
      expect(parseDictationErrorPayload(payload as Record<string, unknown>)).toBeNull();
    },
  );
});
