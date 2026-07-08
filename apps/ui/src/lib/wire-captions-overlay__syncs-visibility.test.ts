/**
 * Captions overlay visibility sync tests.
 */
import { beforeEach, describe, expect, it, vi } from "vitest";

import { INITIAL_TRANSCRIPT_STATE, applyCaptureStarted, transcriptStore } from "./transcript-store";
import { createSettingsStore } from "./settings-store";
import { wireCaptionsOverlay } from "./wire-captions-overlay";

const invoke = vi.fn();

vi.mock("@tauri-apps/api/core", () => ({
  invoke: (...args: unknown[]) => invoke(...args),
}));

const baseSettings = {
  vaultDir: null,
  pushToTalkHotkey: ["F9"] as const,
  keepAudio: false,
  disclosureReminder: true,
  killSwitch: false,
  instantExecuteWhitelist: [] as const,
  activeTemplate: "auto",
  customTemplates: [] as const,
  onboardingComplete: true,
  detectionAutoStartSources: [] as const,
  autostopSilenceS: 60,
  liveCaptionsOverlay: true,
  aecEnabled: false,
  liveTranslationLang: "",
};

describe("wireCaptionsOverlay", () => {
  beforeEach(() => {
    invoke.mockReset();
    invoke.mockResolvedValue(undefined);
    transcriptStore.setState(INITIAL_TRANSCRIPT_STATE);
  });

  it("shows overlay when capture is live and setting enabled", () => {
    const settingsStore = createSettingsStore();
    settingsStore.setState({
      settings: { ...baseSettings, pushToTalkHotkey: ["F9"] },
      settingsPhase: "ready",
      settingsError: null,
      killSwitchEngaged: false,
      routing: [],
      templateOptions: [],
      ledgerPhase: "loading",
      ledgerError: null,
      ledger: null,
      devicesPhase: "pending",
      devicesError: null,
      devices: [],
      devicesSource: "pending",
      selectedInputDeviceId: null,
      selectedOutputDeviceId: null,
    });

    const unwire = wireCaptionsOverlay(settingsStore);
    expect(invoke).not.toHaveBeenCalled();

    applyCaptureStarted(transcriptStore, "m-1", Date.now());
    expect(invoke).toHaveBeenCalledWith("set_captions_overlay_visible", { visible: true });

    unwire();
    expect(invoke).toHaveBeenLastCalledWith("set_captions_overlay_visible", { visible: false });
  });

  it("does not show overlay when disabled in settings", () => {
    const settingsStore = createSettingsStore();
    settingsStore.setState({
      settings: { ...baseSettings, pushToTalkHotkey: ["F9"], liveCaptionsOverlay: false },
      settingsPhase: "ready",
      settingsError: null,
      killSwitchEngaged: false,
      routing: [],
      templateOptions: [],
      ledgerPhase: "loading",
      ledgerError: null,
      ledger: null,
      devicesPhase: "pending",
      devicesError: null,
      devices: [],
      devicesSource: "pending",
      selectedInputDeviceId: null,
      selectedOutputDeviceId: null,
    });

    const unwire = wireCaptionsOverlay(settingsStore);
    applyCaptureStarted(transcriptStore, "m-1", Date.now());
    expect(invoke).not.toHaveBeenCalled();
    unwire();
  });
});
