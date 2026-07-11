/**
 * Fail-closed tests for the streaming model-download + google-connect event
 * parsers. A corrupt frame must never move a progress bar or fake a success.
 */
import { describe, expect, it } from "vitest";
import {
  parseGoogleCompleted,
  parseModelsCompleted,
  parseModelsFailed,
  parseModelsProgress,
} from "./models-download-events";

describe("parseModelsProgress", () => {
  it("accepts a progress frame with a known total and verified flag", () => {
    expect(
      parseModelsProgress({ file: "parakeet.bin", received_bytes: 50, total_bytes: 100, sha256_verified: true }),
    ).toEqual({ file: "parakeet.bin", receivedBytes: 50, totalBytes: 100, sha256Verified: true });
  });

  it("accepts a null total (unknown size) and null verified", () => {
    expect(
      parseModelsProgress({ file: "m", received_bytes: 10, total_bytes: null, sha256_verified: null }),
    ).toEqual({ file: "m", receivedBytes: 10, totalBytes: null, sha256Verified: null });
  });

  it.each<[string, unknown]>([
    ["file empty", { file: "", received_bytes: 1, total_bytes: null, sha256_verified: null }],
    ["received negative", { file: "m", received_bytes: -1, total_bytes: null, sha256_verified: null }],
    ["total a string", { file: "m", received_bytes: 1, total_bytes: "100", sha256_verified: null }],
    ["verified a string", { file: "m", received_bytes: 1, total_bytes: 100, sha256_verified: "yes" }],
  ])("rejects %s", (_label, payload) => {
    expect(parseModelsProgress(payload as Record<string, unknown>)).toBeNull();
  });
});

describe("parseModelsFailed / parseModelsCompleted", () => {
  it("parses a failure", () => {
    expect(parseModelsFailed({ file: "m", message: "network down" })).toEqual({
      file: "m",
      message: "network down",
    });
  });

  it("parses a completion with a string files list (legacy)", () => {
    expect(parseModelsCompleted({ ok: true, files: ["a", "b"] })).toEqual({ ok: true, files: ["a", "b"] });
  });

  it("parses the engine object-shaped files list to filenames", () => {
    expect(
      parseModelsCompleted({
        ok: true,
        files: [
          {
            file: "ggml-large-v3-turbo.bin",
            bytes: 1623828593,
            sha256: "abc",
            sha256_verified: true,
          },
          { file: "silero_vad.onnx", bytes: 100, sha256: null, sha256_verified: null },
        ],
      }),
    ).toEqual({
      ok: true,
      files: ["ggml-large-v3-turbo.bin", "silero_vad.onnx"],
    });
  });

  it("accepts a mixed string/object files list", () => {
    expect(
      parseModelsCompleted({ ok: true, files: ["parakeet.bin", { file: "silero_vad.onnx" }] }),
    ).toEqual({ ok: true, files: ["parakeet.bin", "silero_vad.onnx"] });
  });

  it("rejects a completion whose files contains a bare number (fail closed)", () => {
    expect(parseModelsCompleted({ ok: true, files: ["a", 2] })).toBeNull();
  });

  it("rejects an object file entry missing a non-empty file field", () => {
    expect(parseModelsCompleted({ ok: true, files: [{ bytes: 1 }] })).toBeNull();
    expect(parseModelsCompleted({ ok: true, files: [{ file: "" }] })).toBeNull();
  });

  it("rejects a completion with a non-boolean ok", () => {
    expect(parseModelsCompleted({ ok: "yes", files: [] })).toBeNull();
  });
});

describe("parseGoogleCompleted", () => {
  it("parses a connect result", () => {
    expect(parseGoogleCompleted({ ok: true, message: "Connected." })).toEqual({
      ok: true,
      message: "Connected.",
    });
  });

  it("rejects a missing message", () => {
    expect(parseGoogleCompleted({ ok: false })).toBeNull();
  });
});
