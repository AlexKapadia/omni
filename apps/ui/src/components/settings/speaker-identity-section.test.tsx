import { afterEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { createSettingsStore } from "../../lib/settings-store";
import { SpeakerIdentitySection } from "./speaker-identity-section";

vi.mock("../../lib/speaker-enroll-repository", () => ({
  enrollSpeaker: vi.fn().mockResolvedValue({ voiceEnrolled: false }),
}));

vi.mock("../../lib/record-voice-sample", () => ({
  recordVoiceSampleWavBase64: vi.fn().mockResolvedValue("base64audio"),
}));

import { enrollSpeaker } from "../../lib/speaker-enroll-repository";

afterEach(cleanup);

describe("SpeakerIdentitySection", () => {
  it("saves display name via speaker.enroll", async () => {
    const store = createSettingsStore();
    store.setState({
      settings: {
        vaultDir: null,
        pushToTalkHotkey: ["F9"],
        keepAudio: false,
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
        summaryModelId: "gemini-2.5-flash",
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
      micDeviceId: "",
      },
      settingsPhase: "ready",
      killSwitchEngaged: false,
      routing: [],
      templateOptions: [],
      ledgerPhase: "loading",
      ledger: null,
      ledgerError: null,
      settingsError: null,
    });
    const update = vi.fn().mockResolvedValue({ ok: true, message: null });

    render(<SpeakerIdentitySection store={store} update={update} />);
    // The group is relabelled to the plain "Your voice" in the rehaul.
    expect(screen.getByRole("region", { name: "Your voice" })).toBeTruthy();
    fireEvent.change(screen.getByLabelText("Speaker display name"), {
      target: { value: "Alex" },
    });
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Save name" }));
    });
    expect(enrollSpeaker).toHaveBeenCalledWith("Alex", undefined);
    expect(update).toHaveBeenCalledWith({ speakerIdentity: "Alex" });
  });

  it("syncs the input when speakerIdentity in the store changes", () => {
    const store = createSettingsStore();
    store.setState({
      settings: {
        vaultDir: null,
        pushToTalkHotkey: ["F9"],
        keepAudio: false,
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
        summaryModelId: "gemini-2.5-flash",
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
      micDeviceId: "",
      },
      settingsPhase: "ready",
      killSwitchEngaged: false,
      routing: [],
      templateOptions: [],
      ledgerPhase: "loading",
      ledger: null,
      ledgerError: null,
      settingsError: null,
    });

    render(<SpeakerIdentitySection store={store} update={vi.fn()} />);
    const input = screen.getByLabelText("Speaker display name") as HTMLInputElement;
    expect(input.value).toBe("Me");

    act(() => {
      store.setState({
        settings: {
          ...store.getState().settings!,
          speakerIdentity: "Jordan",
        },
      });
    });
    expect(input.value).toBe("Jordan");
  });
});
