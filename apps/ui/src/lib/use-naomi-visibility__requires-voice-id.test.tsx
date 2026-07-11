/**
 * Naomi nav visibility requires preference + Cartesia key + non-empty voice id.
 */
import { afterEach, describe, expect, it } from "vitest";
import { cleanup, renderHook } from "@testing-library/react";
import { apiKeysStore, INITIAL_API_KEYS_STATE } from "./api-keys-store";
import { appSettingsStore } from "./settings-store";
import { setNaomiEnabledPreference, useNaomiVisibility } from "./use-naomi-visibility";

afterEach(() => {
  cleanup();
  localStorage.clear();
  apiKeysStore.setState({ ...INITIAL_API_KEYS_STATE });
  appSettingsStore.setState({ settings: null });
});

function setCartesiaSaved(saved: boolean): void {
  apiKeysStore.setState({
    keys: {
      ...apiKeysStore.getState().keys,
      cartesia: { saved, lastFour: saved ? "abcd" : null },
    },
  });
}

describe("useNaomiVisibility", () => {
  it("hides Naomi when Cartesia voice id is empty even if key + preference are on", () => {
    setNaomiEnabledPreference(true);
    setCartesiaSaved(true);
    appSettingsStore.setState({
      settings: { cartesiaVoiceId: "   " } as never,
    });

    const { result } = renderHook(() => useNaomiVisibility());
    expect(result.current.preferenceEnabled).toBe(true);
    expect(result.current.showNaomi).toBe(false);
  });

  it("shows Naomi when preference, Cartesia key, and voice id are all set", () => {
    setNaomiEnabledPreference(true);
    setCartesiaSaved(true);
    appSettingsStore.setState({
      settings: { cartesiaVoiceId: "voice-abc" } as never,
    });

    const { result } = renderHook(() => useNaomiVisibility());
    expect(result.current.showNaomi).toBe(true);
  });
});
