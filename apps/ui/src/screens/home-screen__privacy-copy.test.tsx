/**
 * Home privacy copy must not claim "completely offline" when cloud AI is configured.
 */
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import {
  appSettingsStore,
  createInitialSettingsState,
} from "../lib/settings-store";
import type { EngineSettings } from "../lib/setup-settings-payloads";
import { HomeScreen } from "./home-screen";
import { localPrivacyCopy } from "./home-privacy-copy";

afterEach(() => {
  cleanup();
  appSettingsStore.setState(createInitialSettingsState(), true);
});

function baseSettings(overrides: Partial<EngineSettings> = {}): EngineSettings {
  return {
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
    autostopSilenceS: 60,
    liveCaptionsOverlay: true,
    aecEnabled: false,
    liveTranslationLang: "",
    summaryLanguage: "",
    summaryModelId: "llama3.2",
    speakerIdentity: "Alex",
    speakerVoiceEnrolled: false,
    dictationCleanupStyle: "classic",
    sttEngine: "parakeet",
    sttModelId: "",
    sttOpenaiBaseUrl: "",
    selectionTranslationLang: "English",
    ollamaBaseUrl: "http://127.0.0.1:11434",
    summaryProvider: "ollama",
    autoSummary: false,
    cartesiaVoiceId: "",
    micDeviceId: "",
    ...overrides,
  };
}

describe("localPrivacyCopy", () => {
  it("uses strong local copy when STT and summary are on-device", () => {
    const copy = localPrivacyCopy(baseSettings());
    expect(copy.title).toBe("Local-first privacy");
    expect(copy.body).toMatch(/on this device/i);
    expect(copy.body).not.toMatch(/completely offline/i);
  });

  it("uses optional-cloud copy when summaryProvider is cloud", () => {
    const copy = localPrivacyCopy(baseSettings({ summaryProvider: "gemini" }));
    expect(copy.title).toBe("Local-first with optional cloud AI");
    expect(copy.body).not.toMatch(/completely offline|no third part/i);
  });

  it("uses optional-cloud copy when sttEngine is openai_compatible", () => {
    const copy = localPrivacyCopy(
      baseSettings({ sttEngine: "openai_compatible", summaryProvider: "ollama" }),
    );
    expect(copy.title).toBe("Local-first with optional cloud AI");
  });
});

describe("HomeScreen privacy panel", () => {
  beforeEach(() => {
    appSettingsStore.setState({
      ...createInitialSettingsState(),
      settingsPhase: "ready",
      settings: baseSettings({ summaryProvider: "anthropic" }),
    });
  });

  it("renders honest optional-cloud copy when cloud summary is configured", () => {
    render(
      <HomeScreen onNavigate={() => undefined} onStartCapture={() => undefined} />,
    );
    expect(screen.getByText("Local-first with optional cloud AI")).toBeTruthy();
    expect(screen.queryByText("100% Local Privacy")).toBeNull();
    expect(screen.queryByText(/completely offline/i)).toBeNull();
    // Header subtitle must not claim "entirely on this device" when cloud is on.
    expect(screen.queryByText(/entirely on this device/i)).toBeNull();
    expect(
      screen.getAllByText(/Local-first: capture and vault stay on this device/i).length,
    ).toBeGreaterThan(0);
  });
});
