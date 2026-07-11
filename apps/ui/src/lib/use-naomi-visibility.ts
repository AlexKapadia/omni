/**
 * Single source for whether Naomi appears in nav / can be opened.
 * Preference is local (UI chrome); Cartesia key presence comes from the
 * engine-backed api-keys store; voice id comes from settings. All three
 * must be true — a key without a voice id cannot speak.
 */
import { useEffect, useState } from "react";
import { useStore } from "zustand";

import { apiKeysStore } from "./api-keys-store";
import { appSettingsStore } from "./settings-store";

const STORAGE_KEY = "omni_naomi_enabled";
const TOGGLE_EVENT = "naomi-toggle";

export function readNaomiEnabledPreference(): boolean {
  if (typeof localStorage === "undefined") return false;
  return localStorage.getItem(STORAGE_KEY) === "true";
}

export function setNaomiEnabledPreference(enabled: boolean): void {
  localStorage.setItem(STORAGE_KEY, enabled ? "true" : "false");
  window.dispatchEvent(new Event(TOGGLE_EVENT));
}

export function useNaomiVisibility(): {
  readonly preferenceEnabled: boolean;
  readonly showNaomi: boolean;
  readonly setPreferenceEnabled: (enabled: boolean) => void;
} {
  const [preferenceEnabled, setPreference] = useState(readNaomiEnabledPreference);
  const cartesiaSaved = useStore(apiKeysStore, (s) => s.keys.cartesia?.saved === true);
  const cartesiaVoiceId = useStore(
    appSettingsStore,
    (s) => s.settings?.cartesiaVoiceId ?? "",
  );

  useEffect(() => {
    const sync = (): void => setPreference(readNaomiEnabledPreference());
    window.addEventListener(TOGGLE_EVENT, sync);
    return () => window.removeEventListener(TOGGLE_EVENT, sync);
  }, []);

  const cartesiaVoiceReady = Boolean(cartesiaVoiceId.trim());

  return {
    preferenceEnabled,
    showNaomi: preferenceEnabled && cartesiaSaved && cartesiaVoiceReady,
    setPreferenceEnabled: setNaomiEnabledPreference,
  };
}
