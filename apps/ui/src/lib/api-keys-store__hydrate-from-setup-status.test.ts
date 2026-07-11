/**
 * Hydrate api-keys store from setup.status key PRESENCE flags (booleans only —
 * never key material). After restart, Naomi / Settings must see saved=true.
 */
import { describe, expect, it } from "vitest";
import {
  createApiKeysStore,
  hydrateApiKeysFromSetupStatus,
  INITIAL_API_KEYS_STATE,
} from "./api-keys-store";
import type { KeyProvider } from "./setup-settings-commands";

const ALL_FALSE: Readonly<Record<KeyProvider, boolean>> = {
  groq: false,
  gemini: false,
  anthropic: false,
  openai: false,
  openrouter: false,
  azure_openai: false,
  cartesia: false,
};

describe("hydrateApiKeysFromSetupStatus", () => {
  it("marks present providers saved with a masked lastFour placeholder", () => {
    const store = createApiKeysStore();
    hydrateApiKeysFromSetupStatus(store, {
      ...ALL_FALSE,
      groq: true,
      cartesia: true,
    });
    expect(store.getState().keys.groq).toEqual({ saved: true, lastFour: "••••" });
    expect(store.getState().keys.cartesia).toEqual({ saved: true, lastFour: "••••" });
    expect(store.getState().keys.gemini).toEqual({ saved: false, lastFour: null });
  });

  it("clears saved flags when setup.status says the key is absent", () => {
    const store = createApiKeysStore();
    store.setState({
      ...INITIAL_API_KEYS_STATE,
      keys: {
        ...INITIAL_API_KEYS_STATE.keys,
        anthropic: { saved: true, lastFour: "abcd" },
      },
    });
    hydrateApiKeysFromSetupStatus(store, { ...ALL_FALSE, anthropic: false });
    expect(store.getState().keys.anthropic).toEqual({ saved: false, lastFour: null });
  });
});
