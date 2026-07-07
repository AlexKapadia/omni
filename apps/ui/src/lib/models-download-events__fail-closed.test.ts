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

  it("parses a completion with a files list", () => {
    expect(parseModelsCompleted({ ok: true, files: ["a", "b"] })).toEqual({ ok: true, files: ["a", "b"] });
  });

  it("rejects a completion whose files contains a non-string (fail closed)", () => {
    expect(parseModelsCompleted({ ok: true, files: ["a", 2] })).toBeNull();
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
