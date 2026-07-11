/**
 * Cloud STT free-text fields keep local drafts while typing; persist on blur.
 */
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { TranscriptionBackendSection } from "./transcription-backend-section";
import { createSettingsStore } from "../../lib/settings-store";
import type { EngineSettings } from "../../lib/setup-settings-payloads";
import { installJsdomMatchMediaShim } from "../../test-support/install-jsdom-match-media-shim";

beforeAll(installJsdomMatchMediaShim);
afterEach(cleanup);

vi.mock("../../lib/setup-settings-repository", () => ({
  getSetupStatus: vi.fn(async () => ({
    keys: {
      groq: true,
      gemini: true,
      anthropic: false,
      openai: false,
      openrouter: false,
      azure_openai: false,
      cartesia: false,
    },
    vault: { configured: true, path: "C:/vault" },
    models: [],
    googleConnected: false,
    microsoftConnected: false,
    onboardingComplete: true,
    setupComplete: true,
  })),
  startModelsDownload: vi.fn(async () => undefined),
  cancelModelsDownload: vi.fn(async () => undefined),
  deleteModelFile: vi.fn(async () => undefined),
}));

vi.mock("../../lib/setup-settings-transport", () => ({
  requestSetupCommand: vi.fn(),
  subscribeToModelsDownload: () => () => undefined,
}));

vi.mock("../../lib/open-models-folder", () => ({
  openModelsFolderAndReveal: vi.fn(async () => undefined),
}));

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
  sttEngine: "openai_compatible",
  sttModelId: "whisper-1",
  sttOpenaiBaseUrl: "https://api.openai.com/v1",
  selectionTranslationLang: "",
  summaryModelId: "llama3.2",
  ollamaBaseUrl: "http://127.0.0.1:11434",
  summaryProvider: "ollama",
  autoSummary: false,
      cartesiaVoiceId: "",
      micDeviceId: "",
};

describe("TranscriptionBackendSection cloud free-text fields", () => {
  it("does not call update on every keystroke for endpoint or model id", async () => {
    const store = createSettingsStore();
    store.setState({ settings: { ...BASE }, settingsPhase: "ready" });
    const update = vi.fn(async () => ({ ok: true, message: null }));
    render(<TranscriptionBackendSection store={store} update={update} />);
    const endpoint = screen.getByLabelText("Cloud endpoint");
    const model = screen.getByLabelText("Cloud model id");
    await act(async () => {
      fireEvent.change(endpoint, { target: { value: "https://api.openai.com/v" } });
      fireEvent.change(model, { target: { value: "whisper-" } });
    });
    expect((endpoint as HTMLInputElement).value).toBe("https://api.openai.com/v");
    expect((model as HTMLInputElement).value).toBe("whisper-");
    expect(update).not.toHaveBeenCalled();
  });

  it("persists endpoint and model id on blur", async () => {
    const store = createSettingsStore();
    store.setState({ settings: { ...BASE }, settingsPhase: "ready" });
    const update = vi.fn(async () => ({ ok: true, message: null }));
    render(<TranscriptionBackendSection store={store} update={update} />);
    const endpoint = screen.getByLabelText("Cloud endpoint");
    const model = screen.getByLabelText("Cloud model id");
    await act(async () => {
      fireEvent.change(endpoint, { target: { value: "https://example.com/v1" } });
      fireEvent.blur(endpoint);
      fireEvent.change(model, { target: { value: "whisper-1-hd" } });
      fireEvent.blur(model);
    });
    expect(update).toHaveBeenCalledWith({ sttOpenaiBaseUrl: "https://example.com/v1" });
    expect(update).toHaveBeenCalledWith({ sttModelId: "whisper-1-hd" });
  });
});
