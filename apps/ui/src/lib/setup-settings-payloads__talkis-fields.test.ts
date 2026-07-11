import { describe, expect, it } from "vitest";
import { parseSettingsGet } from "./setup-settings-payloads";

const BASE = {
  vault_dir: null,
  push_to_talk_hotkey: ["F9"],
  keep_audio: false,
  disclosure_reminder: true,
  kill_switch: false,
  instant_execute_whitelist: [],
  active_template: "meeting",
  custom_templates: [],
  onboarding_complete: true,
  detection_auto_start_sources: [],
  autostop_silence_s: 60,
  live_captions_overlay: true,
  aec_enabled: false,
  live_translation_lang: "",
  summary_language: "",
  speaker_identity: "Me",
  speaker_voice_enrolled: false,
};

const GOOD_GET = {
  settings: BASE,
  kill_switch_engaged: false,
  routing: [],
  template_options: [],
};

function parseSettings(settings: Record<string, unknown>) {
  return parseSettingsGet({ ...GOOD_GET, settings })?.settings ?? null;
}

describe("Talkis integration settings fields", () => {
  it("defaults new fields when omitted", () => {
    const parsed = parseSettings(BASE);
    expect(parsed).toEqual({
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
      speakerIdentity: "Me",
      speakerVoiceEnrolled: false,
      dictationCleanupStyle: "classic",
      sttEngine: "parakeet",
      sttModelId: "",
      sttOpenaiBaseUrl: "",
      selectionTranslationLang: "English",
      summaryModelId: "llama3.2",
      ollamaBaseUrl: "http://127.0.0.1:11434",
      summaryProvider: "ollama",
      autoSummary: false,
      cartesiaVoiceId: "",
      micDeviceId: "",
    });
  });

  it("accepts explicit Talkis integration values", () => {
    const parsed = parseSettings({
      ...BASE,
      dictation_cleanup_style: "tech",
      stt_engine: "whisper",
      stt_model_id: "tiny",
      stt_openai_base_url: "https://api.example.com/v1",
      selection_translation_lang: "French",
    });
    expect(parsed?.dictationCleanupStyle).toBe("tech");
    expect(parsed?.sttEngine).toBe("whisper");
    expect(parsed?.sttModelId).toBe("tiny");
  });

  it("rejects invalid cleanup style", () => {
    expect(parseSettings({ ...BASE, dictation_cleanup_style: "casual" })).toBeNull();
  });

  it("accepts explicit summary provider and auto-summary values", () => {
    const parsed = parseSettings({ ...BASE, summary_provider: "gemini", auto_summary: true });
    expect(parsed?.summaryProvider).toBe("gemini");
    expect(parsed?.autoSummary).toBe(true);
  });

  it("rejects an unrecognised summary provider (deny by default)", () => {
    expect(parseSettings({ ...BASE, summary_provider: "unknown-provider" })).toBeNull();
  });

  it("defaults micDeviceId to empty when omitted", () => {
    const parsed = parseSettings(BASE);
    expect(parsed?.micDeviceId).toBe("");
  });

  it("accepts an explicit mic_device_id", () => {
    const parsed = parseSettings({ ...BASE, mic_device_id: "3:Headset Microphone" });
    expect(parsed?.micDeviceId).toBe("3:Headset Microphone");
  });
});
