/**
 * Settings tests for the instant-execute whitelist (deny by default), the
 * hotkey capture, and the custom-templates editor — each wired to the REAL
 * settings.update. The whitelist is a security surface: every intent must
 * default OFF and enabling one must persist the exact intent-type array.
 */
import { afterEach, beforeAll, beforeEach, describe, expect, it } from "vitest";
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { SettingsScreen } from "./settings-screen";
import { createApiKeysStore, type ApiKeysStore } from "../lib/api-keys-store";
import {
  applyLedger,
  applySettingsResult,
  createSettingsStore,
  patchSettings,
  type SettingsStore,
} from "../lib/settings-store";
import type { EngineSettings, KeyValidationResult, SettingsGetResult } from "../lib/setup-settings-payloads";
import type { LedgerSummary } from "../lib/ledger-summary-payload";
import type { SettingsUpdater } from "../lib/settings-actions";
import { INSTANT_INTENT_TYPES } from "../lib/setup-settings-commands";
import { installJsdomMatchMediaShim } from "../test-support/install-jsdom-match-media-shim";

beforeAll(installJsdomMatchMediaShim);
afterEach(cleanup);

const READY: SettingsGetResult = {
  settings: {
    vaultDir: "C:/vault",
    pushToTalkHotkey: ["Ctrl", "Shift", "Space"],
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
  killSwitchEngaged: false,
  routing: [],
  templateOptions: [{ templateId: "meeting", displayName: "Meeting notes", builtin: true }],
};

const EMPTY_LEDGER: LedgerSummary = {
  byProvider: [],
  byTask: [],
  totals: { totalCalls: 0, promptTokens: 0, completionTokens: 0, totalCostUsd: "0" },
  recent: [],
};

let settings: SettingsStore;
let keys: ApiKeysStore;
let updates: Partial<EngineSettings>[];

const fakeValidator = (): Promise<KeyValidationResult> =>
  Promise.resolve({ provider: "groq", valid: true, message: "ok", latencyMs: 1 });

beforeEach(() => {
  settings = createSettingsStore();
  applySettingsResult(settings, READY);
  applyLedger(settings, EMPTY_LEDGER);
  keys = createApiKeysStore();
  updates = [];
});

const recordingUpdate: SettingsUpdater = async (partial) => {
  updates.push(partial);
  patchSettings(settings, partial);
  return { ok: true, message: null };
};

function renderScreen() {
  return render(
    <SettingsScreen
      store={settings}
      keysStore={keys}
      vault={{ persistKey: () => Promise.resolve() }}
      validator={fakeValidator}
      update={recordingUpdate}
      bootstrap={() => undefined}
    />,
  );
}

/** The whitelist, hotkey, and automation controls live under Advanced. */
async function openAdvanced(): Promise<void> {
  await act(async () => {
    fireEvent.click(screen.getByRole("tab", { name: "Advanced" }));
  });
}

describe("auto-run safe actions whitelist (deny by default)", () => {
  it("every intent defaults OFF", async () => {
    renderScreen();
    await openAdvanced();
    const whitelistToggles = screen
      .getAllByRole("switch")
      .filter((t) => (t.getAttribute("aria-label") ?? "").startsWith("Auto-run "));
    expect(whitelistToggles).toHaveLength(INSTANT_INTENT_TYPES.length);
    for (const t of whitelistToggles) expect(t.getAttribute("aria-checked")).toBe("false");
  });

  it("enabling one persists exactly that intent type", async () => {
    renderScreen();
    await openAdvanced();
    const toggle = screen.getByRole("switch", { name: "Auto-run Create Google Calendar events" });
    await act(async () => fireEvent.click(toggle));
    expect(updates).toContainEqual({ instantExecuteWhitelist: ["create_event"] });
    expect(toggle.getAttribute("aria-checked")).toBe("true");
    // Honest: create_event only writes Google Calendar (not Outlook/"your calendar").
    expect(toggle.getAttribute("aria-label")).toBe("Auto-run Create Google Calendar events");
    expect(screen.getByText(/adds events to Google Calendar/)).toBeTruthy();
    expect(screen.getByText(/meeting actions still need Approve/)).toBeTruthy();
    expect(screen.getByText(/Whitelisted dictation commands skip the approval card/)).toBeTruthy();
  });
});

describe("hotkey capture", () => {
  it("records a real combination and persists push_to_talk_hotkey", async () => {
    renderScreen();
    await openAdvanced();
    expect(screen.getByText("Ctrl")).toBeTruthy();
    await act(async () => fireEvent.click(screen.getByRole("button", { name: "Change" })));
    const cancel = screen.getByRole("button", { name: "Cancel" });
    await act(async () => fireEvent.keyDown(cancel, { key: "k", ctrlKey: true }));
    expect(updates).toContainEqual({ pushToTalkHotkey: ["Ctrl", "K"] });
  });
});

describe("custom templates editor", () => {
  it("adds then removes a custom template, persisting each time", async () => {
    renderScreen();
    const input = screen.getByLabelText("New custom template name");
    fireEvent.change(input, { target: { value: "Deep dive" } });
    await act(async () => fireEvent.click(screen.getByRole("button", { name: "Add" })));
    expect(updates).toContainEqual({ customTemplates: ["Deep dive"] });
    // It now shows with a Remove control; removing persists the empty list.
    await act(async () => fireEvent.click(screen.getByRole("button", { name: "Remove Deep dive" })));
    expect(updates).toContainEqual({ customTemplates: [] });
  });

  it("switching the active template persists active_template as template_id", async () => {
    renderScreen();
    // Engine template_options already include customs with snake_case ids.
    await act(async () => {
      settings.setState({
        templateOptions: [
          { templateId: "meeting", displayName: "Meeting notes", builtin: true },
          { templateId: "deep_dive", displayName: "Deep dive", builtin: false },
        ],
      });
      patchSettings(settings, { customTemplates: ["Deep dive"] });
    });
    const select = screen.getByLabelText("Note template") as HTMLSelectElement;
    fireEvent.change(select, { target: { value: "deep_dive" } });
    expect(updates).toContainEqual({ activeTemplate: "deep_dive" });
    // Display names must not appear as option values (engine rejects them).
    expect([...select.options].map((o) => o.value)).not.toContain("Deep dive");
  });

  it("renaming the active custom template persists the new template_id", async () => {
    renderScreen();
    await act(async () => {
      settings.setState({
        templateOptions: [
          { templateId: "meeting", displayName: "Meeting notes", builtin: true },
          { templateId: "deep_dive", displayName: "Deep dive", builtin: false },
        ],
      });
      patchSettings(settings, {
        customTemplates: ["Deep dive"],
        activeTemplate: "deep_dive",
      });
    });
    await act(async () => fireEvent.click(screen.getByRole("button", { name: "Rename" })));
    fireEvent.change(screen.getByLabelText("Rename Deep dive"), {
      target: { value: "Deep dive notes" },
    });
    await act(async () => fireEvent.click(screen.getByRole("button", { name: "Save" })));
    expect(updates).toContainEqual({
      customTemplates: ["Deep dive notes"],
      activeTemplate: "deep_dive_notes",
    });
  });
});
