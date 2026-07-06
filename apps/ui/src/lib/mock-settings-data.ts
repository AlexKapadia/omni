/**
 * Initial settings — REAL devices arrive from the engine's `devices.list`
 * command (engine-devices.ts) after mount; only the LEDGER rows remain
 * synthetic until the router's real cost/latency ledger is surfaced (M7).
 *
 * Clearly-marked mock per the swappable-data-layer contract: identical shapes
 * to the future engine payloads. The routing table itself is REAL project
 * policy (tri-provider router; transcription/embeddings are on-device only) —
 * only the ledger numbers are placeholders. Costs are integer cents (exact
 * arithmetic mandate).
 */
import type { SettingsState } from "./settings-store";

/** The app singleton settings store's initial state. */
export function buildMockInitialSettings(): SettingsState {
  return {
    // Devices start PENDING and honest-empty: the real enumeration lands via
    // devices.list, or the section says "unavailable" — never invented names.
    devicesSource: "pending",
    microphone: "",
    microphoneOptions: [],
    // Real policy: system audio always follows the Windows default render
    // device via WASAPI loopback — it is informational, not selectable.
    systemAudioDevice: "",
    pushToTalkKeys: ["Ctrl", "Shift", "Space"],
    activeTemplate: "Meeting notes",
    templateOptions: ["Meeting notes", "1:1", "Interview", "Standup"],
    // Real routing policy (deny-by-default allowed sets), mock current picks.
    routing: [
      { task: "transcription", provider: "local", allowed: ["local"] },
      { task: "embeddings", provider: "local", allowed: ["local"] },
      { task: "live answers", provider: "groq", allowed: ["groq", "gemini", "claude"] },
      { task: "note enhancement", provider: "gemini", allowed: ["groq", "gemini", "claude"] },
      { task: "action parsing", provider: "claude", allowed: ["groq", "gemini", "claude"] },
    ],
    // MOCK ledger rows — the real router writes this from its cost ledger.
    ledger: [
      { task: "note enhancement", calls: 92, tokens: 1_210_000, p50Seconds: 3.8, costCents: 412 },
      { task: "live answers", calls: 214, tokens: 246_000, p50Seconds: 1.4, costCents: 96 },
      { task: "action parsing", calls: 68, tokens: 114_000, p50Seconds: 2.1, costCents: 91 },
    ],
    keepAudio: false, // security default: audio discarded after transcription
    disclosureReminder: true,
    killSwitch: false,
  };
}

/** Honest ledger caption: mock numbers must never masquerade as real spend. */
export const LEDGER_MOCK_CAPTION = "sample data — the live ledger arrives with the router";
