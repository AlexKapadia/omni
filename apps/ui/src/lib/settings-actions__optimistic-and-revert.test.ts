/**
 * settings-actions tests: loads fill or honestly fail the store; a control
 * update is optimistic but REVERTS with the engine's message on refusal (a
 * control never shows a state the engine did not accept); a kill-switch change
 * re-reads settings.get to reflect the true engaged state.
 */
import { describe, expect, it } from "vitest";
import { loadLedger, loadSettings, updateSetting } from "./settings-actions";
import { applySettingsResult, createSettingsStore } from "./settings-store";
import type { SettingsGetResult } from "./setup-settings-payloads";

const BASE: SettingsGetResult = {
  settings: {
    vaultDir: "C:/v",
    pushToTalkHotkey: ["Ctrl", "Space"],
    keepAudio: false,
    disclosureReminder: true,
    killSwitch: false,
    instantExecuteWhitelist: [],
    activeTemplate: "meeting",
    customTemplates: [],
    onboardingComplete: true,
    detectionAutoStartSources: [],
    autostopSilenceS: 60,
  },
  killSwitchEngaged: false,
  routing: [],
  templateOptions: [],
};

const WIRE_GET = {
  settings: {
    vault_dir: "C:/v",
    push_to_talk_hotkey: ["Ctrl", "Space"],
    keep_audio: false,
    disclosure_reminder: true,
    kill_switch: true,
    instant_execute_whitelist: [],
    active_template: "meeting",
    custom_templates: [],
    onboarding_complete: true,
    detection_auto_start_sources: [],
    autostop_silence_s: 60,
  },
  kill_switch_engaged: true, // the engine reports it engaged now
  routing: [],
  template_options: [],
};

describe("loadSettings / loadLedger", () => {
  it("fills the store from a valid settings.get", async () => {
    const store = createSettingsStore();
    await loadSettings(store, async () => WIRE_GET);
    expect(store.getState().settingsPhase).toBe("ready");
    expect(store.getState().killSwitchEngaged).toBe(true);
  });

  it("marks the load failed honestly when the engine refuses", async () => {
    const store = createSettingsStore();
    await loadSettings(store, async () => {
      throw new Error("engine offline");
    });
    expect(store.getState().settingsPhase).toBe("error");
    expect(store.getState().settingsError).toBe("engine offline");
  });

  it("marks the ledger failed on a malformed reply", async () => {
    const store = createSettingsStore();
    await loadLedger(store, 20, async () => ({ by_provider: "nope" }));
    expect(store.getState().ledgerPhase).toBe("error");
  });
});

describe("updateSetting optimistic + revert", () => {
  it("applies optimistically and confirms on ok", async () => {
    const store = createSettingsStore();
    applySettingsResult(store, BASE);
    const result = await updateSetting(store, { keepAudio: true }, async (name) => {
      if (name === "settings.update") return { applied: { keep_audio: true } };
      throw new Error(`unexpected ${name}`);
    });
    expect(result.ok).toBe(true);
    expect(store.getState().settings!.keepAudio).toBe(true);
  });

  it("REVERTS the optimistic change and surfaces the message on refusal", async () => {
    const store = createSettingsStore();
    applySettingsResult(store, BASE);
    const result = await updateSetting(store, { keepAudio: true }, async () => {
      throw new Error("settings_error: disk full");
    });
    expect(result.ok).toBe(false);
    expect(result.message).toContain("disk full");
    expect(store.getState().settings!.keepAudio).toBe(false); // reverted
  });

  it("a kill-switch change re-reads settings.get for the true engaged state", async () => {
    const store = createSettingsStore();
    applySettingsResult(store, BASE);
    expect(store.getState().killSwitchEngaged).toBe(false);
    const result = await updateSetting(store, { killSwitch: true }, async (name) => {
      if (name === "settings.update") return { applied: { kill_switch: true } };
      if (name === "settings.get") return WIRE_GET;
      throw new Error(`unexpected ${name}`);
    });
    expect(result.ok).toBe(true);
    expect(store.getState().killSwitchEngaged).toBe(true); // reflected from the engine
  });
});
