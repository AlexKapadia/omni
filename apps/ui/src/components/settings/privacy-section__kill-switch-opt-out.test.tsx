/**
 * Kill switch can be omitted from PrivacySection (Recordings tab) so it
 * lives only on System/Pro.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { createSettingsStore } from "../../lib/settings-store";
import type { EngineSettings } from "../../lib/setup-settings-payloads";
import { PrivacySection } from "./privacy-section";

afterEach(cleanup);

function baseSettings(): EngineSettings {
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
  };
}

describe("PrivacySection showKillSwitch", () => {
  it("hides Pause all cloud AI when showKillSwitch is false", () => {
    const store = createSettingsStore();
    store.setState({ settings: baseSettings(), settingsPhase: "ready" });
    render(
      <PrivacySection
        store={store}
        update={vi.fn().mockResolvedValue({ ok: true, message: null })}
        showKillSwitch={false}
      />,
    );
    expect(screen.queryByRole("switch", { name: "Pause all cloud AI" })).toBeNull();
    expect(screen.getByRole("switch", { name: "Keep audio after transcription" })).toBeTruthy();
  });

  it("shows Pause all cloud AI by default", () => {
    const store = createSettingsStore();
    store.setState({ settings: baseSettings(), settingsPhase: "ready" });
    render(
      <PrivacySection
        store={store}
        update={vi.fn().mockResolvedValue({ ok: true, message: null })}
      />,
    );
    expect(screen.getByRole("switch", { name: "Pause all cloud AI" })).toBeTruthy();
  });
});
