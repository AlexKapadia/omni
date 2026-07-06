/**
 * Zustand store for Settings: devices, hotkeys, templates, AI router table,
 * cost/latency ledger, and the privacy controls.
 *
 * Initial values come from mock-settings-data.ts (clearly-marked mock); the
 * M2+ engine settings service persists the same shapes. Every mutation here
 * validates its input — the router refuses providers a task does not allow
 * (deny by default), mirroring the engine-side routing policy.
 *
 * Security bindings surfaced in this store:
 * - keepAudio defaults FALSE — audio is discarded after transcription.
 * - killSwitch halts all external model calls when engaged (fail closed on
 *   egress; on-device capture/notes stay available).
 */
import { createStore, type StoreApi } from "zustand";

/** Real routing targets per the project spec (Groq / Gemini / Claude) plus
 *  "local" for the on-device models. The design doc's provider copy is stale
 *  by contract — layouts from the doc, data from the engine contracts. */
export type RoutingProvider = "local" | "groq" | "gemini" | "claude";

export interface RoutingRow {
  readonly task: string;
  readonly provider: RoutingProvider;
  /** Providers this task may route to. On-device-only tasks allow just "local". */
  readonly allowed: readonly RoutingProvider[];
}

export interface LedgerRow {
  readonly task: string;
  readonly calls: number;
  readonly tokens: number;
  readonly p50Seconds: number | null; // null = not applicable
  /** Cost in integer cents — exact arithmetic, never floating dollars. */
  readonly costCents: number;
}

export interface SettingsState {
  readonly microphone: string;
  readonly microphoneOptions: readonly string[];
  readonly systemAudioDevice: string;
  readonly pushToTalkKeys: readonly string[];
  readonly activeTemplate: string;
  readonly templateOptions: readonly string[];
  readonly routing: readonly RoutingRow[];
  readonly ledger: readonly LedgerRow[];
  readonly keepAudio: boolean; // default false — discard after transcription
  readonly disclosureReminder: boolean;
  readonly killSwitch: boolean; // true = all external calls refused
}

export type SettingsStore = StoreApi<SettingsState>;

export function createSettingsStore(initial: SettingsState): SettingsStore {
  return createStore<SettingsState>(() => initial);
}

export function setMicrophone(store: SettingsStore, device: string): void {
  store.setState((state) =>
    // Deny by default: only a device from the enumerated list is accepted.
    state.microphoneOptions.includes(device) ? { microphone: device } : state,
  );
}

export function setActiveTemplate(store: SettingsStore, template: string): void {
  store.setState((state) =>
    state.templateOptions.includes(template) ? { activeTemplate: template } : state,
  );
}

export function setPushToTalkKeys(store: SettingsStore, keys: readonly string[]): void {
  if (keys.length === 0) return; // an empty hotkey would silently disable capture
  store.setState({ pushToTalkKeys: keys });
}

export function setRoutingProvider(
  store: SettingsStore,
  task: string,
  provider: RoutingProvider,
): void {
  store.setState((state) => ({
    routing: state.routing.map((row) =>
      // Deny by default: a provider outside the task's allowed set is refused.
      row.task === task && row.allowed.includes(provider) ? { ...row, provider } : row,
    ),
  }));
}

export function setKeepAudio(store: SettingsStore, keep: boolean): void {
  store.setState({ keepAudio: keep });
}

export function setDisclosureReminder(store: SettingsStore, on: boolean): void {
  store.setState({ disclosureReminder: on });
}

export function setKillSwitch(store: SettingsStore, engaged: boolean): void {
  store.setState({ killSwitch: engaged });
}

export interface LedgerTotals {
  readonly calls: number;
  readonly tokens: number;
  readonly costCents: number;
}

/** Exact integer sums — the total row is computed, never hand-written. */
export function ledgerTotals(rows: readonly LedgerRow[]): LedgerTotals {
  return rows.reduce<LedgerTotals>(
    (acc, row) => ({
      calls: acc.calls + row.calls,
      tokens: acc.tokens + row.tokens,
      costCents: acc.costCents + row.costCents,
    }),
    { calls: 0, tokens: 0, costCents: 0 },
  );
}
