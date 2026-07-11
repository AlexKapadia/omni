/**
 * disclosureReminder gates the on-device disclosure copy in the capture bar.
 */
import { afterEach, beforeAll, describe, expect, it } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { CaptureBar } from "./capture-bar";
import { createSettingsStore } from "../../lib/settings-store";
import type { EngineSettings } from "../../lib/setup-settings-payloads";
import { installJsdomMatchMediaShim } from "../../test-support/install-jsdom-match-media-shim";

beforeAll(installJsdomMatchMediaShim);
afterEach(cleanup);

const BASE: EngineSettings = {
  vaultDir: "C:/vault",
  pushToTalkHotkey: ["Ctrl", "Shift", "Space"],
  keepAudio: true,
  disclosureReminder: true,
  killSwitch: false,
  instantExecuteWhitelist: [],
  activeTemplate: "auto",
  customTemplates: [],
  onboardingComplete: true,
  detectionAutoStartSources: [],
  autostopSilenceS: 0,
  liveCaptionsOverlay: false,
  aecEnabled: false,
  liveTranslationLang: "",
  summaryLanguage: "",
  speakerIdentity: "Me",
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

describe("CaptureBar disclosure reminder", () => {
  it("shows the on-device disclosure when disclosureReminder is true", () => {
    const store = createSettingsStore();
    store.setState({ settings: { ...BASE, disclosureReminder: true }, settingsPhase: "ready" });
    render(<CaptureBar elapsedSeconds={12} settingsStore={store} />);
    expect(screen.getByText("mic + system audio · on-device")).toBeTruthy();
  });

  it("hides the on-device disclosure when disclosureReminder is false", () => {
    const store = createSettingsStore();
    store.setState({ settings: { ...BASE, disclosureReminder: false }, settingsPhase: "ready" });
    render(<CaptureBar elapsedSeconds={12} settingsStore={store} />);
    expect(screen.queryByText("mic + system audio · on-device")).toBeNull();
  });
});
