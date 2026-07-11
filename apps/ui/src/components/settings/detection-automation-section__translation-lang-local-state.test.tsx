/**
 * Live translation language keeps a local draft while typing; persists on blur.
 */
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { DetectionAutomationSection } from "./detection-automation-section";
import { createSettingsStore } from "../../lib/settings-store";
import type { EngineSettings } from "../../lib/setup-settings-payloads";
import { installJsdomMatchMediaShim } from "../../test-support/install-jsdom-match-media-shim";

beforeAll(installJsdomMatchMediaShim);
afterEach(cleanup);

const BASE: EngineSettings = {
  vaultDir: "C:/vault",
  pushToTalkHotkey: ["F9"],
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

describe("DetectionAutomationSection live translation lang", () => {
  it("does not call update on every keystroke", async () => {
    const store = createSettingsStore();
    store.setState({ settings: { ...BASE }, settingsPhase: "ready" });
    const update = vi.fn(async () => ({ ok: true, message: null }));
    render(<DetectionAutomationSection store={store} update={update} />);
    const input = screen.getByLabelText("Live translation target language");
    await act(async () => {
      fireEvent.change(input, { target: { value: "Spa" } });
    });
    expect((input as HTMLInputElement).value).toBe("Spa");
    expect(update).not.toHaveBeenCalled();
  });

  it("persists on blur", async () => {
    const store = createSettingsStore();
    store.setState({ settings: { ...BASE }, settingsPhase: "ready" });
    const update = vi.fn(async () => ({ ok: true, message: null }));
    render(<DetectionAutomationSection store={store} update={update} />);
    const input = screen.getByLabelText("Live translation target language");
    await act(async () => {
      fireEvent.change(input, { target: { value: "Spanish" } });
      fireEvent.blur(input);
    });
    expect(update).toHaveBeenCalledWith({ liveTranslationLang: "Spanish" });
  });
});
