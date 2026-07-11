/**
 * Settings screen tests (real engine data): the binding key-masking invariant
 * (a saved key value NEVER appears in the DOM), privacy defaults (keep-audio
 * OFF) wired to settings.update, the kill-switch engaged disclosure, the
 * read-only router matrix from REAL routing, and the REAL ledger rendering.
 */
import { afterEach, beforeAll, beforeEach, describe, expect, it } from "vitest";
import { act, cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { SettingsScreen } from "./settings-screen";
import { createApiKeysStore, type ApiKeysStore } from "../lib/api-keys-store";
import {
  applyLedger,
  applySettingsResult,
  createSettingsStore,
  patchSettings,
  setKillSwitchEngaged,
  type SettingsStore,
} from "../lib/settings-store";
import type { EngineSettings, SettingsGetResult } from "../lib/setup-settings-payloads";
import type { LedgerSummary } from "../lib/ledger-summary-payload";
import type { SettingsUpdater } from "../lib/settings-actions";
import type { KeyValidationResult } from "../lib/setup-settings-payloads";
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
  routing: [
    { task: "transcription", onDevice: true, attempts: [], budgetMs: 0 },
    {
      task: "note enhancement",
      onDevice: false,
      attempts: [{ provider: "gemini", model: "flash" }],
      budgetMs: 8000,
    },
  ],
  templateOptions: [
    { templateId: "meeting", displayName: "Meeting notes", builtin: true },
    { templateId: "one-on-one", displayName: "1:1", builtin: true },
  ],
};

const LEDGER: LedgerSummary = {
  byProvider: [],
  byTask: [
    {
      task: "note enhancement",
      totalCalls: 92,
      promptTokens: 1_200_000,
      completionTokens: 10_000,
      totalCostUsd: "4.12",
      avgLatencyMs: 3800,
    },
  ],
  totals: { totalCalls: 92, promptTokens: 1_200_000, completionTokens: 10_000, totalCostUsd: "4.12" },
  recent: [],
};

let settings: SettingsStore;
let keys: ApiKeysStore;
let updates: Partial<EngineSettings>[];

const fakeValidator = (): Promise<KeyValidationResult> =>
  Promise.resolve({ provider: "groq", valid: true, message: "ok", latencyMs: 12 });

beforeEach(() => {
  settings = createSettingsStore();
  applySettingsResult(settings, READY);
  applyLedger(settings, LEDGER);
  keys = createApiKeysStore();
  updates = [];
});

/** A fake updater that records the partial and applies it (no socket). */
const recordingUpdate: SettingsUpdater = async (partial) => {
  updates.push(partial);
  patchSettings(settings, partial);
  return { ok: true, message: null };
};

function renderScreen(vault = { persistKey: () => Promise.resolve() }) {
  return render(
    <SettingsScreen
      store={settings}
      keysStore={keys}
      vault={vault}
      validator={fakeValidator}
      update={recordingUpdate}
      bootstrap={() => undefined}
    />,
  );
}

/** Reveal the Advanced tier (AI providers, usage, automation, devices). */
async function openAdvanced(): Promise<void> {
  await act(async () => {
    fireEvent.click(screen.getByRole("tab", { name: "Advanced" }));
  });
}

describe("two-tier settings (Essentials default, Advanced on demand)", () => {
  it("defaults to Essentials and switching reveals Advanced-only groups", async () => {
    renderScreen();
    // Essentials is the selected tab and shows an Essentials-only group.
    expect(screen.getByRole("tab", { name: "Essentials" }).getAttribute("aria-selected")).toBe("true");
    expect(screen.getByRole("tab", { name: "Advanced" }).getAttribute("aria-selected")).toBe("false");
    expect(screen.getByRole("region", { name: "Your voice" })).toBeTruthy();
    // Advanced-only groups are NOT reachable until the user switches tiers.
    expect(screen.queryByRole("region", { name: "API keys" })).toBeNull();
    expect(screen.queryByRole("region", { name: "Diagnostics" })).toBeNull();

    await openAdvanced();
    expect(screen.getByRole("tab", { name: "Advanced" }).getAttribute("aria-selected")).toBe("true");
    expect(screen.getByRole("region", { name: "API keys" })).toBeTruthy();
    expect(screen.getByRole("region", { name: "Diagnostics" })).toBeTruthy();
    // Essentials content is no longer mounted once Advanced is active.
    expect(screen.queryByRole("region", { name: "Your voice" })).toBeNull();
  });
});

describe("API key masking (binding security invariant)", () => {
  const SECRET = "sk-ant-Zx9Qw7Rt5Yu3Io1PR2Qw";

  it("the saved key value NEVER appears in the DOM afterwards", async () => {
    renderScreen();
    await openAdvanced();
    const input = screen.getByLabelText("Claude API key") as HTMLInputElement;
    expect(input.type).toBe("password");
    fireEvent.change(input, { target: { value: SECRET } });
    // Submit the Claude row's OWN form (four providers each have a Save key).
    await act(async () => {
      fireEvent.submit(input.closest("form")!);
    });
    expect(document.body.innerHTML).not.toContain(SECRET);
    expect(screen.getByText(/•+ R2Qw/)).toBeTruthy();
    expect(screen.queryByLabelText("Claude API key")).toBeNull();
  });
});

describe("privacy controls wired to settings.update", () => {
  it("keep-audio reflects the persisted setting and toggling persists keep_audio", async () => {
    renderScreen();
    const toggle = screen.getByRole("switch", { name: "Keep audio after transcription" });
    expect(toggle.getAttribute("aria-checked")).toBe("false"); // fixture opts out explicitly
    await act(async () => {
      fireEvent.click(toggle);
    });
    expect(updates).toContainEqual({ keepAudio: true });
    expect(toggle.getAttribute("aria-checked")).toBe("true");
  });

  it("pause-all-cloud-AI persists and the paused state discloses in the router card", async () => {
    renderScreen();
    // The de-jargoned control lives in Essentials; the disclosure lives in the
    // Advanced routing matrix — both reflect the ENGINE state, not the toggle.
    await act(async () => {
      fireEvent.click(screen.getByRole("switch", { name: "Pause all cloud AI" }));
    });
    expect(updates).toContainEqual({ killSwitch: true });
    await openAdvanced();
    expect(screen.queryByText(/Cloud AI is paused/)).toBeNull();
    act(() => setKillSwitchEngaged(settings, true));
    expect(screen.getByText(/Cloud AI is paused/)).toBeTruthy();
    expect(screen.getByText(/Local Ollama still works/)).toBeTruthy();
  });
});

describe("router matrix is read-only real policy", () => {
  it("renders the resolved routes and exposes NO radios (read-only)", async () => {
    renderScreen();
    await openAdvanced();
    const router = within(screen.getByRole("region", { name: "AI providers" }));
    expect(router.getByText("note enhancement")).toBeTruthy();
    expect(router.getByText("gemini")).toBeTruthy();
    expect(router.getByText("on-device")).toBeTruthy();
    expect(screen.queryByRole("radio")).toBeNull(); // no picking — read-only
  });
});

describe("real ledger", () => {
  it("renders a real task row and its exact cost string", async () => {
    renderScreen();
    await openAdvanced();
    const ledger = within(screen.getByRole("region", { name: "Cost and latency" }));
    expect(ledger.getByText("note enhancement")).toBeTruthy();
    // "$4.12" is the verbatim engine string, in both the task and total rows.
    expect(ledger.getAllByText("$4.12").length).toBe(2);
    expect(ledger.getAllByText("1.21M").length).toBe(2); // 1.2M prompt + 10K completion
  });
});
