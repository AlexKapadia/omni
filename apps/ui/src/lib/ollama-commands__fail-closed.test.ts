/**
 * Fail-closed tests for the Ollama list/pull/ping parsers. Payloads mirror
 * the engine's real wire shapes exactly (engine/protocol/ollama_command_payloads.py,
 * engine/router/ollama_http_client.py) — a malformed or divergent frame must
 * never populate the picker, move a progress bar, or fake a "Connected."
 */
import { describe, expect, it } from "vitest";

import {
  parseOllamaModelsList,
  parseOllamaPingResult,
  parseOllamaPullCompleted,
  parseOllamaPullFailed,
  parseOllamaPullProgress,
} from "./ollama-commands";

describe("parseOllamaModelsList", () => {
  it("parses a list of installed models with sizes", () => {
    expect(
      parseOllamaModelsList({ models: [{ name: "llama3.2", size: 2_000_000 }, { name: "gemma3:1b", size: 800_000 }] }),
    ).toEqual([
      { name: "llama3.2", sizeBytes: 2_000_000 },
      { name: "gemma3:1b", sizeBytes: 800_000 },
    ]);
  });

  it("parses an empty list (no models pulled yet)", () => {
    expect(parseOllamaModelsList({ models: [] })).toEqual([]);
  });

  it("accepts a null size", () => {
    expect(parseOllamaModelsList({ models: [{ name: "m", size: null }] })).toEqual([
      { name: "m", sizeBytes: null },
    ]);
  });

  it.each<[string, unknown]>([
    ["models is not an array", { models: "llama3.2" }],
    ["models key missing", {}],
    ["an entry is not an object", { models: ["llama3.2"] }],
    ["an entry has an empty name", { models: [{ name: "", size: 1 }] }],
    ["an entry is missing a name", { models: [{ size: 1 }] }],
    ["size is a string", { models: [{ name: "m", size: "big" }] }],
  ])("rejects %s", (_label, payload) => {
    expect(parseOllamaModelsList(payload as Record<string, unknown>)).toBeNull();
  });
});

describe("parseOllamaPullProgress", () => {
  it("accepts a progress beat with a known total", () => {
    expect(parseOllamaPullProgress({ model: "llama3.2", received_bytes: 512, total_bytes: 2048 })).toEqual({
      model: "llama3.2",
      receivedBytes: 512,
      totalBytes: 2048,
    });
  });

  it("accepts a null total (Ollama has not reported layer size yet)", () => {
    expect(parseOllamaPullProgress({ model: "m", received_bytes: 0, total_bytes: null })).toEqual({
      model: "m",
      receivedBytes: 0,
      totalBytes: null,
    });
  });

  it.each<[string, unknown]>([
    ["model empty", { model: "", received_bytes: 1, total_bytes: null }],
    ["received_bytes negative", { model: "m", received_bytes: -1, total_bytes: null }],
    ["received_bytes a string", { model: "m", received_bytes: "1", total_bytes: null }],
    ["total_bytes a string", { model: "m", received_bytes: 1, total_bytes: "2048" }],
    ["received_bytes missing", { model: "m", total_bytes: null }],
  ])("rejects %s", (_label, payload) => {
    expect(parseOllamaPullProgress(payload as Record<string, unknown>)).toBeNull();
  });
});

describe("parseOllamaPullFailed / parseOllamaPullCompleted", () => {
  it("parses a failure", () => {
    expect(parseOllamaPullFailed({ model: "llama3.2", message: "connection refused" })).toEqual({
      model: "llama3.2",
      message: "connection refused",
    });
  });

  it("parses a completion", () => {
    expect(parseOllamaPullCompleted({ model: "llama3.2", ok: true })).toEqual({
      model: "llama3.2",
      ok: true,
    });
  });

  it("rejects a completion with a non-boolean ok", () => {
    expect(parseOllamaPullCompleted({ model: "llama3.2", ok: "yes" })).toBeNull();
  });

  it("rejects a failure missing the model", () => {
    expect(parseOllamaPullFailed({ message: "network down" })).toBeNull();
  });
});

describe("parseOllamaPingResult", () => {
  it("parses a success reply carrying a version", () => {
    expect(parseOllamaPingResult({ ok: true, version: "0.5.1" })).toEqual({
      ok: true,
      version: "0.5.1",
      error: null,
    });
  });

  it("tolerates a missing version field on success (real Ollama builds vary)", () => {
    expect(parseOllamaPingResult({ ok: true })).toEqual({ ok: true, version: null, error: null });
  });

  it("parses a fail-closed connection error", () => {
    expect(parseOllamaPingResult({ ok: false, error: "connection refused" })).toEqual({
      ok: false,
      version: null,
      error: "connection refused",
    });
  });

  it("rejects a payload with no ok field at all", () => {
    expect(parseOllamaPingResult({ version: "0.5.1" })).toBeNull();
  });

  it("rejects a non-boolean ok", () => {
    expect(parseOllamaPingResult({ ok: "true" })).toBeNull();
  });
});
