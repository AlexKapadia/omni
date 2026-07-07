/**
 * validateApiKey tests: "✓ Valid" (status "valid") follows ONLY a genuine
 * success; a false verdict is "invalid", a thrown error is "error" — never a
 * rosy default. Saving a key resets a stale validation verdict to idle.
 */
import { describe, expect, it } from "vitest";
import {
  createApiKeysStore,
  saveApiKey,
  validateApiKey,
  type KeyValidator,
} from "./api-keys-store";
import type { KeyValidationResult } from "./setup-settings-payloads";

const okValidator: KeyValidator = (provider): Promise<KeyValidationResult> =>
  Promise.resolve({ provider, valid: true, message: "reachable", latencyMs: 33 });

describe("validateApiKey", () => {
  it("marks valid with the engine message + latency on a real success", async () => {
    const store = createApiKeysStore();
    const ok = await validateApiKey(store, okValidator, "groq");
    expect(ok).toBe(true);
    expect(store.getState().validation.groq).toEqual({
      status: "valid",
      message: "reachable",
      latencyMs: 33,
    });
  });

  it("marks invalid (never valid) when the verdict is false", async () => {
    const store = createApiKeysStore();
    const ok = await validateApiKey(
      store,
      (provider) => Promise.resolve({ provider, valid: false, message: "401 unauthorized", latencyMs: null }),
      "gemini",
    );
    expect(ok).toBe(false);
    expect(store.getState().validation.gemini.status).toBe("invalid");
    expect(store.getState().validation.gemini.message).toBe("401 unauthorized");
  });

  it("marks error (fail closed) when validation throws", async () => {
    const store = createApiKeysStore();
    const ok = await validateApiKey(
      store,
      () => Promise.reject(new Error("engine offline")),
      "anthropic",
    );
    expect(ok).toBe(false);
    expect(store.getState().validation.anthropic.status).toBe("error");
    expect(store.getState().validation.anthropic.message).toBe("engine offline");
  });

  it("saving a key resets its stale validation verdict to idle", async () => {
    const store = createApiKeysStore();
    await validateApiKey(store, okValidator, "cartesia");
    expect(store.getState().validation.cartesia.status).toBe("valid");
    await saveApiKey(store, { persistKey: () => Promise.resolve() }, "cartesia", "sk-newkey-12345");
    expect(store.getState().validation.cartesia.status).toBe("idle"); // must re-validate
  });
});
