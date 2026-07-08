/**
 * Fail-closed parser tests for settings.get / setup.status / keys.validate.
 * Every reply is untrusted: a malformed field must reject the WHOLE payload
 * (null), never coerce a value into the UI. Whitelist parsing drops unknown
 * intents (deny by default) but rejects a corrupt (non-array) shape.
 */
import { describe, expect, it } from "vitest";
import {
  parseKeyValidation,
  parseSettingsGet,
  parseSetupStatus,
} from "./setup-settings-payloads";

const GOOD_SETTINGS = {
  vault_dir: "C:/vault",
  push_to_talk_hotkey: ["Ctrl", "Shift", "Space"],
  keep_audio: false,
  disclosure_reminder: true,
  kill_switch: false,
  instant_execute_whitelist: ["create_event", "draft_email"],
  active_template: "meeting",
  custom_templates: ["Deep dive"],
  onboarding_complete: true,
  detection_auto_start_sources: ["zoom", "teams"],
  autostop_silence_s: 60,
};

const GOOD_GET = {
  settings: GOOD_SETTINGS,
  kill_switch_engaged: false,
  routing: [
    { task: "note", on_device: false, attempts: [{ provider: "groq", model: "x" }], budget_ms: 8000 },
    { task: "transcription", on_device: true, attempts: [], budget_ms: 0 },
  ],
  template_options: [{ template_id: "meeting", display_name: "Meeting notes", builtin: true }],
};

describe("parseSettingsGet", () => {
  it("accepts the pinned shape and keeps values exactly", () => {
    const result = parseSettingsGet(GOOD_GET);
    expect(result).not.toBeNull();
    expect(result!.settings.vaultDir).toBe("C:/vault");
    expect(result!.settings.pushToTalkHotkey).toEqual(["Ctrl", "Shift", "Space"]);
    expect(result!.settings.instantExecuteWhitelist).toEqual(["create_event", "draft_email"]);
    expect(result!.settings.detectionAutoStartSources).toEqual(["zoom", "teams"]);
    expect(result!.settings.autostopSilenceS).toBe(60);
    expect(result!.routing[0]!.attempts[0]).toEqual({ provider: "groq", model: "x" });
  });

  it("null vault_dir is allowed (not yet chosen)", () => {
    const result = parseSettingsGet({ ...GOOD_GET, settings: { ...GOOD_SETTINGS, vault_dir: null } });
    expect(result!.settings.vaultDir).toBeNull();
  });

  it("accepts a string hotkey and splits it", () => {
    const result = parseSettingsGet({
      ...GOOD_GET,
      settings: { ...GOOD_SETTINGS, push_to_talk_hotkey: "Ctrl+Shift+Space" },
    });
    expect(result!.settings.pushToTalkHotkey).toEqual(["Ctrl", "Shift", "Space"]);
  });

  it("DENY BY DEFAULT: drops an unknown whitelist intent, keeps the known ones", () => {
    const result = parseSettingsGet({
      ...GOOD_GET,
      settings: { ...GOOD_SETTINGS, instant_execute_whitelist: ["create_event", "launch_missiles"] },
    });
    expect(result!.settings.instantExecuteWhitelist).toEqual(["create_event"]);
  });

  it.each<[string, unknown]>([
    ["not an object", null],
    ["settings missing", { ...GOOD_GET, settings: undefined }],
    ["keep_audio not boolean", { ...GOOD_GET, settings: { ...GOOD_SETTINGS, keep_audio: "no" } }],
    ["whitelist not an array", { ...GOOD_GET, settings: { ...GOOD_SETTINGS, instant_execute_whitelist: "all" } }],
    ["custom_templates has a non-string", { ...GOOD_GET, settings: { ...GOOD_SETTINGS, custom_templates: [1] } }],
    ["vault_dir a number", { ...GOOD_GET, settings: { ...GOOD_SETTINGS, vault_dir: 7 } }],
    ["kill_switch_engaged missing", { ...GOOD_GET, kill_switch_engaged: undefined }],
    ["routing attempt missing provider", { ...GOOD_GET, routing: [{ task: "n", on_device: false, attempts: [{ model: "x" }], budget_ms: 1 }] }],
    ["routing budget not a number", { ...GOOD_GET, routing: [{ task: "n", on_device: false, attempts: [], budget_ms: "fast" }] }],
    ["template option missing builtin", { ...GOOD_GET, template_options: [{ template_id: "m", display_name: "M" }] }],
  ])("rejects %s", (_label, payload) => {
    expect(parseSettingsGet(payload as Record<string, unknown>)).toBeNull();
  });
});

const GOOD_STATUS = {
  keys: { groq: true, gemini: false, anthropic: false, cartesia: false },
  vault: { configured: true, path: "C:/vault" },
  models: [{ file: "parakeet.bin", present: true, bytes: 1234 }],
  google_connected: false,
  onboarding_complete: false,
  setup_complete: false,
};

describe("parseSetupStatus", () => {
  it("accepts the pinned shape", () => {
    const status = parseSetupStatus(GOOD_STATUS);
    expect(status!.keys.groq).toBe(true);
    expect(status!.vault).toEqual({ configured: true, path: "C:/vault" });
    expect(status!.models[0]).toEqual({ file: "parakeet.bin", present: true, bytes: 1234 });
  });

  it("allows a null vault path (not yet configured)", () => {
    const status = parseSetupStatus({ ...GOOD_STATUS, vault: { configured: false, path: null } });
    expect(status!.vault.path).toBeNull();
  });

  it.each<[string, unknown]>([
    ["keys missing a provider", { ...GOOD_STATUS, keys: { groq: true, gemini: false, anthropic: false } }],
    ["a key flag not boolean", { ...GOOD_STATUS, keys: { ...GOOD_STATUS.keys, cartesia: "yes" } }],
    ["model bytes not a number", { ...GOOD_STATUS, models: [{ file: "m", present: true, bytes: "big" }] }],
    ["vault configured not boolean", { ...GOOD_STATUS, vault: { configured: "yes", path: null } }],
    ["setup_complete missing", { ...GOOD_STATUS, setup_complete: undefined }],
  ])("rejects %s", (_label, payload) => {
    expect(parseSetupStatus(payload as Record<string, unknown>)).toBeNull();
  });
});

describe("parseKeyValidation", () => {
  it("accepts a valid verdict with latency", () => {
    expect(parseKeyValidation({ valid: true, message: "ok", latency_ms: 42 })).toEqual({
      valid: true,
      message: "ok",
      latencyMs: 42,
    });
  });

  it("accepts a null latency", () => {
    expect(parseKeyValidation({ valid: false, message: "bad key", latency_ms: null })).toEqual({
      valid: false,
      message: "bad key",
      latencyMs: null,
    });
  });

  it.each<[string, unknown]>([
    ["valid not boolean", { valid: "yes", message: "m", latency_ms: 1 }],
    ["message missing", { valid: true, latency_ms: 1 }],
    ["latency a string", { valid: true, message: "m", latency_ms: "fast" }],
  ])("rejects %s", (_label, payload) => {
    expect(parseKeyValidation(payload as Record<string, unknown>)).toBeNull();
  });
});
