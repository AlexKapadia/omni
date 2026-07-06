/**
 * Security tests for the API-key store: the plaintext key must never be
 * retained in store state (only saved/lastFour metadata), validation is
 * fail-closed, and a vault failure never reports a key as saved.
 */
import { describe, expect, it } from "vitest";
import {
  createApiKeysStore,
  saveApiKey,
  type ApiKeyVault,
} from "./api-keys-store";

const SECRET = "sk-test-Zx9Qw7Rt5Yu3Io1P";

function recordingVault(): ApiKeyVault & { received: string[] } {
  const received: string[] = [];
  return {
    received,
    persistKey: (_provider, value) => {
      received.push(value);
      return Promise.resolve();
    },
  };
}

describe("saveApiKey", () => {
  it("hands the exact value to the vault ONCE and keeps only metadata", async () => {
    const store = createApiKeysStore();
    const vault = recordingVault();
    const ok = await saveApiKey(store, vault, "anthropic", SECRET);
    expect(ok).toBe(true);
    expect(vault.received).toEqual([SECRET]); // vault got it, exactly once
    // The binding invariant: the plaintext is NOWHERE in the store state.
    expect(JSON.stringify(store.getState())).not.toContain(SECRET);
    expect(store.getState().keys.anthropic).toEqual({ saved: true, lastFour: "Io1P" });
  });

  it("trims surrounding whitespace before persisting (paste artefacts)", async () => {
    const store = createApiKeysStore();
    const vault = recordingVault();
    await saveApiKey(store, vault, "groq", `  ${SECRET}  `);
    expect(vault.received).toEqual([SECRET]);
  });

  it("rejects a too-short key WITHOUT calling the vault (fail closed)", async () => {
    const store = createApiKeysStore();
    const vault = recordingVault();
    expect(await saveApiKey(store, vault, "groq", "abc")).toBe(false);
    expect(vault.received).toHaveLength(0);
    expect(store.getState().keys.groq.saved).toBe(false);
    expect(store.getState().errorMessage).not.toBeNull();
  });

  it("boundary: 7 chars refused, 8 chars accepted", async () => {
    const store = createApiKeysStore();
    const vault = recordingVault();
    expect(await saveApiKey(store, vault, "groq", "a".repeat(7))).toBe(false);
    expect(await saveApiKey(store, vault, "groq", "a".repeat(8))).toBe(true);
  });

  it("rejects internal whitespace (a mangled multi-line paste)", async () => {
    const store = createApiKeysStore();
    const vault = recordingVault();
    expect(await saveApiKey(store, vault, "gemini", "sk-test\nsecond-line")).toBe(false);
    expect(vault.received).toHaveLength(0);
  });

  it("a vault failure never reports the key as saved", async () => {
    const store = createApiKeysStore();
    const failingVault: ApiKeyVault = {
      persistKey: () => Promise.reject(new Error("dpapi unavailable")),
    };
    expect(await saveApiKey(store, failingVault, "anthropic", SECRET)).toBe(false);
    expect(store.getState().keys.anthropic.saved).toBe(false);
    expect(store.getState().errorMessage).not.toBeNull();
    expect(JSON.stringify(store.getState())).not.toContain(SECRET); // even on failure
  });

  it("saving one provider never touches another's state", async () => {
    const store = createApiKeysStore();
    const vault = recordingVault();
    await saveApiKey(store, vault, "groq", SECRET);
    expect(store.getState().keys.gemini).toEqual({ saved: false, lastFour: null });
    expect(store.getState().keys.anthropic).toEqual({ saved: false, lastFour: null });
  });
});
