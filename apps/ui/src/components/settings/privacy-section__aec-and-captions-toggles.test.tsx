/**
 * Privacy toggles for echo cancellation and live captions overlay must
 * call updateSetting with the pinned EngineSettings keys.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { createSettingsStore } from "../../lib/settings-store";
import type { EngineSettings } from "../../lib/setup-settings-payloads";
import { PrivacySection } from "./privacy-section";

afterEach(cleanup);

function baseSettings(partial: Partial<EngineSettings> = {}): EngineSettings {
  return {
    vaultDir: null,
    pushToTalkHotkey: ["F9"],
    keepAudio: true,
    disclosureReminder: false,
    killSwitch: false,
    instantExecuteWhitelist: [],
    activeTemplate: "auto",
    customTemplates: [],
    onboardingComplete: true,
    detectionAutoStartSources: [],
    autostopSilenceS: 60,
    liveCaptionsOverlay: true,
    aecEnabled: false,
    liveTranslationLang: "",
    summaryLanguage: "",
    speakerIdentity: "",
    speakerVoiceEnrolled: false,
    dictationCleanupStyle: "classic",
    sttEngine: "parakeet",
    sttModelId: "",
    sttOpenaiBaseUrl: "",
    selectionTranslationLang: "",
    summaryModelId: "llama3.2",
    ollamaBaseUrl: "http://127.0.0.1:11434",
    summaryProvider: "ollama",
    autoSummary: false,
      cartesiaVoiceId: "",
      micDeviceId: "",
    ...partial,
  };
}

describe("PrivacySection aec + captions toggles", () => {
  it("toggles echo cancellation and live captions overlay via update", async () => {
    const store = createSettingsStore();
    store.setState({
      settings: baseSettings({ aecEnabled: false, liveCaptionsOverlay: true }),
      settingsPhase: "ready",
    });
    const update = vi.fn().mockResolvedValue({ ok: true, message: null });

    render(<PrivacySection store={store} update={update} />);

    fireEvent.click(screen.getByRole("switch", { name: "Echo cancellation" }));
    expect(update).toHaveBeenCalledWith({ aecEnabled: true });

    fireEvent.click(screen.getByRole("switch", { name: "Live captions overlay" }));
    expect(update).toHaveBeenCalledWith({ liveCaptionsOverlay: false });
  });
});
