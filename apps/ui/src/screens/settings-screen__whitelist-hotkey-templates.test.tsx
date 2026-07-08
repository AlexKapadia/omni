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

describe("instant-execute whitelist (deny by default)", () => {
  it("every intent defaults OFF", () => {
    renderScreen();
    const whitelistToggles = screen
      .getAllByRole("switch")
      .filter((t) => (t.getAttribute("aria-label") ?? "").startsWith("Instant execute"));
    expect(whitelistToggles).toHaveLength(INSTANT_INTENT_TYPES.length);
    for (const t of whitelistToggles) expect(t.getAttribute("aria-checked")).toBe("false");
  });

  it("enabling one persists exactly that intent type", async () => {
    renderScreen();
    const toggle = screen.getByRole("switch", { name: "Instant execute Create calendar events" });
    await act(async () => fireEvent.click(toggle));
    expect(updates).toContainEqual({ instantExecuteWhitelist: ["create_event"] });
    expect(toggle.getAttribute("aria-checked")).toBe("true");
    // The security copy makes the still-audited effect explicit.
    expect(screen.getByText(/no card — still audited/)).toBeTruthy();
  });
});

describe("hotkey capture", () => {
  it("records a real combination and persists push_to_talk_hotkey", async () => {
    renderScreen();
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

  it("switching the active template persists active_template", async () => {
    renderScreen();
    const select = screen.getByLabelText("Note template") as HTMLSelectElement;
    // Seed a custom option to switch to.
    await act(async () => {
      patchSettings(settings, { customTemplates: ["Deep dive"] });
    });
    fireEvent.change(select, { target: { value: "Deep dive" } });
    expect(updates).toContainEqual({ activeTemplate: "Deep dive" });
  });
});
