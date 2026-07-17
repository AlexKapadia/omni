/**
 * Ollama endpoint input keeps local draft state while typing; only persists
 * on blur (or when the draft is already a valid http(s) URL) — never reverts
 * mid-keystroke via settings.update.
 */
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { SummaryModelSection } from "./summary-model-section";
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

describe("SummaryModelSection Ollama URL", () => {
  it("does not call update on every keystroke for a partial URL", async () => {
    const store = createSettingsStore();
    store.setState({ settings: { ...BASE }, settingsPhase: "ready" });
    const update = vi.fn(async () => ({ ok: true, message: null }));
    render(<SummaryModelSection store={store} update={update} />);
    const input = screen.getByLabelText("Ollama endpoint");
    await act(async () => {
      fireEvent.change(input, { target: { value: "http://127.0.0.1:1" } });
    });
    expect((input as HTMLInputElement).value).toBe("http://127.0.0.1:1");
    expect(update).not.toHaveBeenCalled();
  });

  it("persists a valid URL on blur", async () => {
    const store = createSettingsStore();
    store.setState({ settings: { ...BASE }, settingsPhase: "ready" });
    const update = vi.fn(async () => ({ ok: true, message: null }));
    render(<SummaryModelSection store={store} update={update} />);
    const input = screen.getByLabelText("Ollama endpoint");
    await act(async () => {
      fireEvent.change(input, { target: { value: "http://192.168.1.5:11434" } });
      fireEvent.blur(input);
    });
    expect(update).toHaveBeenCalledWith({ ollamaBaseUrl: "http://192.168.1.5:11434" });
  });
});
