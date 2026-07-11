/**
 * Persisted mic_device_id hydrates the settings-store microphone field on load,
 * and refreshDevices preserves a still-present pick.
 */
import { describe, expect, it } from "vitest";
import { applyDeviceListing, applySettingsResult, createSettingsStore } from "./settings-store";
import type { SettingsGetResult } from "./setup-settings-payloads";

const BASE: SettingsGetResult = {
  settings: {
    vaultDir: "C:/v",
    pushToTalkHotkey: ["F9"],
    keepAudio: true,
    disclosureReminder: true,
    killSwitch: false,
    instantExecuteWhitelist: [],
    activeTemplate: "meeting",
    customTemplates: [],
    onboardingComplete: true,
    detectionAutoStartSources: [],
    autostopSilenceS: 60,
    liveCaptionsOverlay: true,
    aecEnabled: false,
    liveTranslationLang: "",
    summaryLanguage: "",
    summaryModelId: "llama3.2",
    ollamaBaseUrl: "http://127.0.0.1:11434",
    speakerIdentity: "Me",
    speakerVoiceEnrolled: false,
    dictationCleanupStyle: "classic",
    sttEngine: "parakeet",
    sttModelId: "",
    sttOpenaiBaseUrl: "",
    selectionTranslationLang: "English",
    summaryProvider: "ollama",
    autoSummary: false,
    cartesiaVoiceId: "",
    micDeviceId: "9:USB Mic",
  },
  killSwitchEngaged: false,
  routing: [],
  templateOptions: [],
};

describe("micDeviceId hydration", () => {
  it("applySettingsResult copies micDeviceId into the microphone field", () => {
    const store = createSettingsStore();
    applySettingsResult(store, BASE);
    expect(store.getState().microphone).toBe("9:USB Mic");
    expect(store.getState().settings?.micDeviceId).toBe("9:USB Mic");
  });

  it("refreshDevices preserves a matching persisted mic id", () => {
    const store = createSettingsStore();
    applySettingsResult(store, BASE);
    applyDeviceListing(store, {
      microphone: "3:Headset Microphone",
      microphoneOptions: [
        { id: "3:Headset Microphone", name: "Headset Microphone" },
        { id: "9:USB Mic", name: "USB Mic" },
      ],
      systemAudioDevice: "Speakers",
    });
    expect(store.getState().microphone).toBe("9:USB Mic");
  });

  it("empty micDeviceId does not overwrite an existing microphone pick", () => {
    const store = createSettingsStore();
    store.setState({ microphone: "3:Headset Microphone" });
    applySettingsResult(store, {
      ...BASE,
      settings: { ...BASE.settings, micDeviceId: "" },
    });
    expect(store.getState().microphone).toBe("3:Headset Microphone");
  });
});
