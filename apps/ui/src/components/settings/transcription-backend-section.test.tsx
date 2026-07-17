/**
 * Transcription Settings: Meetily-style provider select + Whisper download.
 */
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { TranscriptionBackendSection } from "./transcription-backend-section";
import {
  createSettingsStore,
  type SettingsState,
} from "../../lib/settings-store";
import type { EngineSettings } from "../../lib/setup-settings-payloads";

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
    models: [
      { file: "silero_vad.onnx", present: true, bytes: 1 },
      { file: "parakeet-tdt-0.6b-v2.nemo", present: true, bytes: 1 },
      { file: "ggml-small.bin", present: false, bytes: 0 },
    ],
    googleConnected: false,
    microsoftConnected: false,
    onboardingComplete: true,
    setupComplete: true,
  })),
  startModelsDownload: vi.fn(async () => undefined),
}));

vi.mock("../../lib/setup-settings-transport", () => ({
  requestSetupCommand: vi.fn(),
  subscribeToModelsDownload: () => () => undefined,
}));

function baseSettings(partial: Partial<EngineSettings> = {}): EngineSettings {
  return {
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

describe("TranscriptionBackendSection", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("lets the user pick Whisper and download a size", async () => {
    const { startModelsDownload } = await import("../../lib/setup-settings-repository");
    const updates: unknown[] = [];
    const initial: SettingsState = {
      settingsPhase: "ready",
      settingsError: null,
      settings: baseSettings(),
      killSwitchEngaged: false,
      routing: [],
      templateOptions: [],
      ledgerPhase: "ready",
      ledgerError: null,
      ledger: null,
      devicesSource: "engine",
      microphone: "",
      microphoneOptions: [],
      systemAudioDevice: "",
    };
    const store = createSettingsStore(initial);

    render(
      <TranscriptionBackendSection
        store={store}
        update={async (partial) => {
          updates.push(partial);
          store.setState((s) => ({
            ...s,
            settings: s.settings ? { ...s.settings, ...partial } : s.settings,
          }));
          return { ok: true, message: null };
        }}
      />,
    );

    fireEvent.change(screen.getByRole("combobox", { name: /Transcription provider/i }), {
      target: { value: "whisper" },
    });
    await waitFor(() => {
      expect(updates.some((u) => (u as { sttEngine?: string }).sttEngine === "whisper")).toBe(true);
    });

    const downloadButtons = await screen.findAllByRole("button", { name: /Download/i });
    fireEvent.click(downloadButtons[0]!);
    await waitFor(() => {
      expect(startModelsDownload).toHaveBeenCalledWith(expect.any(Function), {
        bundle: "whisper",
        modelId: expect.any(String),
      });
    });
  });
});
