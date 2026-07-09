/**
 * Adversarial tests for the capture-event payload parsers: every deviation
 * from the pinned engine shapes must fail CLOSED (null), never coerce.
 * Payloads are untrusted input — these are the trust-boundary tests.
 */
import { describe, expect, it } from "vitest";
import {
  parseCaptureDeviceChangedPayload,
  parseCaptureStartedPayload,
  parseCaptureStoppedPayload,
  parseTranscriptFinalPayload,
  parseTranscriptPartialPayload,
} from "./capture-protocol";

const VALID_PARTIAL = { stream: "them", text: "hello", t_start: 1.5, t_end: 2.25, seq: 3 };
const VALID_FINAL = { ...VALID_PARTIAL, segment_id: "seg-1", lag_ms: 240.5 };

describe("parseTranscriptPartialPayload", () => {
  it("accepts the exact pinned shape, verbatim", () => {
    expect(parseTranscriptPartialPayload(VALID_PARTIAL)).toEqual(VALID_PARTIAL);
  });

  it("accepts optional speaker_id and speaker_label", () => {
    expect(
      parseTranscriptPartialPayload({
        ...VALID_PARTIAL,
        speaker_id: "1",
        speaker_label: "Speaker 1",
      }),
    ).toEqual({
      ...VALID_PARTIAL,
      speaker_id: "1",
      speaker_label: "Speaker 1",
    });
  });

  it("accepts empty text (a partial can open with silence)", () => {
    expect(parseTranscriptPartialPayload({ ...VALID_PARTIAL, text: "" })).not.toBeNull();
  });

  it("accepts seq 0 and t_start === t_end (zero-length boundary)", () => {
    expect(
      parseTranscriptPartialPayload({ ...VALID_PARTIAL, seq: 0, t_start: 2, t_end: 2 }),
    ).not.toBeNull();
  });

  it.each<[string, Record<string, unknown>]>([
    ["unknown stream label", { ...VALID_PARTIAL, stream: "system" }],
    ["stream wrong type", { ...VALID_PARTIAL, stream: 1 }],
    ["missing stream", (({ stream: _, ...rest }) => rest)(VALID_PARTIAL)],
    ["text not a string", { ...VALID_PARTIAL, text: 42 }],
    ["text null", { ...VALID_PARTIAL, text: null }],
    ["t_start negative", { ...VALID_PARTIAL, t_start: -0.001 }],
    ["t_start NaN", { ...VALID_PARTIAL, t_start: Number.NaN }],
    ["t_end Infinity", { ...VALID_PARTIAL, t_end: Number.POSITIVE_INFINITY }],
    ["t_end before t_start", { ...VALID_PARTIAL, t_start: 5, t_end: 4.999 }],
    ["seq negative", { ...VALID_PARTIAL, seq: -1 }],
    ["seq fractional", { ...VALID_PARTIAL, seq: 1.5 }],
    ["seq numeric string", { ...VALID_PARTIAL, seq: "3" }],
  ])("rejects %s", (_name, payload) => {
    expect(parseTranscriptPartialPayload(payload)).toBeNull();
  });
});

describe("parseTranscriptFinalPayload", () => {
  it("accepts the exact pinned shape, verbatim", () => {
    expect(parseTranscriptFinalPayload(VALID_FINAL)).toEqual(VALID_FINAL);
  });

  it("accepts optional speaker_id and speaker_label", () => {
    expect(
      parseTranscriptFinalPayload({
        ...VALID_FINAL,
        speaker_id: "2",
        speaker_label: "Speaker 2",
      }),
    ).toEqual({
      ...VALID_FINAL,
      speaker_id: "2",
      speaker_label: "Speaker 2",
    });
  });

  it("accepts lag_ms of exactly 0 (boundary)", () => {
    expect(parseTranscriptFinalPayload({ ...VALID_FINAL, lag_ms: 0 })).not.toBeNull();
  });

  it.each<[string, Record<string, unknown>]>([
    ["missing segment_id", (({ segment_id: _, ...rest }) => rest)(VALID_FINAL)],
    ["empty segment_id", { ...VALID_FINAL, segment_id: "" }],
    ["segment_id wrong type", { ...VALID_FINAL, segment_id: 7 }],
    ["missing lag_ms", (({ lag_ms: _, ...rest }) => rest)(VALID_FINAL)],
    ["lag_ms negative", { ...VALID_FINAL, lag_ms: -1 }],
    ["lag_ms NaN", { ...VALID_FINAL, lag_ms: Number.NaN }],
    ["lag_ms string", { ...VALID_FINAL, lag_ms: "240" }],
    ["core corrupt too (bad stream)", { ...VALID_FINAL, stream: "ME" }],
  ])("rejects %s", (_name, payload) => {
    expect(parseTranscriptFinalPayload(payload)).toBeNull();
  });
});

describe("capture lifecycle payload parsers", () => {
  it("accept exact shapes", () => {
    expect(parseCaptureStartedPayload({ meeting_id: "m1", reason: "command" })).toEqual({
      meeting_id: "m1",
      reason: "command",
    });
    expect(parseCaptureStoppedPayload({ meeting_id: "m1", reason: "error" })).toEqual({
      meeting_id: "m1",
      reason: "error",
    });
    expect(parseCaptureDeviceChangedPayload({ device_name: "Headset", recovered_ms: 84.2 })).toEqual(
      { device_name: "Headset", recovered_ms: 84.2 },
    );
  });

  it.each<[string, Record<string, unknown>]>([
    ["empty meeting_id", { meeting_id: "", reason: "command" }],
    ["missing reason", { meeting_id: "m1" }],
    ["reason wrong type", { meeting_id: "m1", reason: 0 }],
  ])("started/stopped reject %s", (_name, payload) => {
    expect(parseCaptureStartedPayload(payload)).toBeNull();
    expect(parseCaptureStoppedPayload(payload)).toBeNull();
  });

  it.each<[string, Record<string, unknown>]>([
    ["empty device_name", { device_name: "", recovered_ms: 10 }],
    ["negative recovered_ms", { device_name: "X", recovered_ms: -0.01 }],
    ["NaN recovered_ms", { device_name: "X", recovered_ms: Number.NaN }],
  ])("device_changed rejects %s", (_name, payload) => {
    expect(parseCaptureDeviceChangedPayload(payload)).toBeNull();
  });
});
