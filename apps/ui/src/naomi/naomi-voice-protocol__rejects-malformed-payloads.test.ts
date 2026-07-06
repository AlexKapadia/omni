/**
 * Naomi voice payload parsers: fail-closed on EVERY deviation — engine
 * events are untrusted input like all inbound frames (house invariant,
 * lib/protocol.ts style). Plus the pcm base64 decoder's hostile-input
 * hardening in naomi-audio-playback.
 */
import { describe, expect, it } from "vitest";
import { decodePcmFloat32Base64 } from "./naomi-audio-playback";
import {
  parseNaomiAudioChunkPayload,
  parseNaomiAudioDonePayload,
  parseNaomiSpeakingTimestampsPayload,
} from "./naomi-voice-protocol";

const VALID_CHUNK = {
  context_id: "ctx-1",
  seq: 0,
  pcm_b64: "AAAAAA==",
  sample_rate: 24000,
  ttfa_ms: 87.5,
};

describe("naomi.audio.chunk", () => {
  it("accepts the valid shape", () => {
    const parsed = parseNaomiAudioChunkPayload({ ...VALID_CHUNK });
    expect(parsed).toEqual(VALID_CHUNK);
  });
  it("ttfa_ms is optional (null when absent)", () => {
    const { ttfa_ms: _omitted, ...rest } = VALID_CHUNK;
    expect(parseNaomiAudioChunkPayload(rest)?.ttfa_ms).toBeNull();
  });
  it.each([
    ["missing context", { ...VALID_CHUNK, context_id: undefined }],
    ["empty context", { ...VALID_CHUNK, context_id: "" }],
    ["oversized context", { ...VALID_CHUNK, context_id: "x".repeat(129) }],
    ["negative seq", { ...VALID_CHUNK, seq: -1 }],
    ["fractional seq", { ...VALID_CHUNK, seq: 1.5 }],
    ["NaN seq", { ...VALID_CHUNK, seq: Number.NaN }],
    ["empty pcm", { ...VALID_CHUNK, pcm_b64: "" }],
    ["non-string pcm", { ...VALID_CHUNK, pcm_b64: 42 }],
    ["zero sample rate", { ...VALID_CHUNK, sample_rate: 0 }],
    ["negative ttfa", { ...VALID_CHUNK, ttfa_ms: -5 }],
    ["string ttfa", { ...VALID_CHUNK, ttfa_ms: "87" }],
  ])("rejects %s", (_name, payload) => {
    expect(parseNaomiAudioChunkPayload(payload as Record<string, unknown>)).toBeNull();
  });
});

describe("naomi.audio.done", () => {
  it.each(["completed", "cancelled", "error"] as const)("accepts reason %s", (reason) => {
    expect(parseNaomiAudioDonePayload({ context_id: "c", reason })?.reason).toBe(reason);
  });
  it.each([
    ["unknown reason", { context_id: "c", reason: "finished" }],
    ["missing reason", { context_id: "c" }],
    ["numeric detail", { context_id: "c", reason: "error", detail: 42 }],
    ["missing context", { reason: "completed" }],
  ])("rejects %s", (_name, payload) => {
    expect(parseNaomiAudioDonePayload(payload as Record<string, unknown>)).toBeNull();
  });
});

describe("naomi.speaking.timestamps", () => {
  const VALID = {
    context_id: "c",
    words: ["hello", "there"],
    starts_s: [0, 0.4],
    ends_s: [0.35, 0.8],
  };
  it("accepts aligned arrays", () => {
    expect(parseNaomiSpeakingTimestampsPayload({ ...VALID })).toEqual(VALID);
  });
  it.each([
    ["length mismatch words/starts", { ...VALID, starts_s: [0] }],
    ["length mismatch words/ends", { ...VALID, ends_s: [0.35] }],
    ["non-string word", { ...VALID, words: ["hello", 42] }],
    ["negative start", { ...VALID, starts_s: [-0.1, 0.4] }],
    ["NaN end", { ...VALID, ends_s: [0.35, Number.NaN] }],
    ["non-array words", { ...VALID, words: "hello there" }],
  ])("rejects %s (corrupt frames never half-apply)", (_name, payload) => {
    expect(parseNaomiSpeakingTimestampsPayload(payload as Record<string, unknown>)).toBeNull();
  });
});

describe("pcm_f32le base64 decoding — hostile audio can never reach the speakers", () => {
  function encodeFloats(values: number[]): string {
    const bytes = new Uint8Array(new Float32Array(values).buffer);
    let binary = "";
    for (const b of bytes) binary += String.fromCharCode(b);
    return btoa(binary);
  }

  it("round-trips real samples exactly", () => {
    const samples = [0, 0.5, -0.5, 0.999, -1];
    const decoded = decodePcmFloat32Base64(encodeFloats(samples));
    expect(decoded).not.toBeNull();
    expect(Array.from(decoded ?? [])).toEqual(Array.from(new Float32Array(samples)));
  });

  it.each([
    ["not base64", "!!!not-base64!!!"],
    ["empty", ""],
    ["byte count not divisible by 4", btoa("abc")],
  ])("rejects %s", (_name, input) => {
    expect(decodePcmFloat32Base64(input)).toBeNull();
  });

  it("rejects NaN samples (would corrupt the analyser-driven water)", () => {
    expect(decodePcmFloat32Base64(encodeFloats([0.1, Number.NaN, 0.2]))).toBeNull();
  });

  it("rejects Infinity and speaker-slamming magnitudes", () => {
    expect(decodePcmFloat32Base64(encodeFloats([Number.POSITIVE_INFINITY]))).toBeNull();
    expect(decodePcmFloat32Base64(encodeFloats([1000]))).toBeNull();
  });

  it("accepts full-scale audio at the boundary (|s| ≤ 4 headroom)", () => {
    expect(decodePcmFloat32Base64(encodeFloats([4, -4]))).not.toBeNull();
    expect(decodePcmFloat32Base64(encodeFloats([4.0001]))).toBeNull();
  });
});
