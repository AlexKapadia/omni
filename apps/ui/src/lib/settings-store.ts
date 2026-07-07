/**
 * Zustand store for Settings — now REAL engine-backed. Its state is filled by
 * `settings.get` (settings + resolved routing + template options + the live
 * kill-switch state) and `ledger.summary` (the real cost/latency ledger); the
 * device rows still come from the real `devices.list` enumeration. There is no
 * mock data anywhere in this store.
 *
 * This module holds only PURE state + setters (each fail-closed on device
 * picks). The async orchestration — asking the engine, optimistic updates and
 * revert-on-failure — lives in settings-actions.ts so the state stays testable
 * without a socket.
 *
 * Security bindings surfaced here:
 * - keepAudio defaults FALSE in the engine — audio is discarded after
 *   transcription; this store only reflects the engine's truth.
 * - killSwitchEngaged mirrors the engine: when engaged, every external route
 *   is refused (fail closed on egress; on-device capture/notes keep working).
 */
import { createStore, type StoreApi } from "zustand";
import type { EngineSettings, RoutingRow, SettingsGetResult, TemplateOption } from "./setup-settings-payloads";
import type { LedgerSummary } from "./ledger-summary-payload";

export type { EngineSettings, RoutingRow, TemplateOption } from "./setup-settings-payloads";

/** A three-phase async read: awaiting the engine, ready, or honestly failed. */
export type LoadPhase = "loading" | "ready" | "error";

/** Where the device rows came from (real enumeration only, never invented). */
export type DevicesSource = "pending" | "engine" | "unavailable";

export interface SettingsState {
  // settings.get lifecycle
  readonly settingsPhase: LoadPhase;
  readonly settingsError: string | null;
  readonly settings: EngineSettings | null;
  readonly killSwitchEngaged: boolean;
  readonly routing: readonly RoutingRow[];
  readonly templateOptions: readonly TemplateOption[];
  // ledger.summary lifecycle
  readonly ledgerPhase: LoadPhase;
  readonly ledgerError: string | null;
  readonly ledger: LedgerSummary | null;
  // devices (real devices.list flow)
  readonly devicesSource: DevicesSource;
  readonly microphone: string;
  readonly microphoneOptions: readonly string[];
  readonly systemAudioDevice: string;
}

export type SettingsStore = StoreApi<SettingsState>;

/** Honest initial state — everything loading/empty until the engine answers. */
export function createInitialSettingsState(): SettingsState {
  return {
    settingsPhase: "loading",
    settingsError: null,
    settings: null,
    killSwitchEngaged: false,
    routing: [],
    templateOptions: [],
    ledgerPhase: "loading",
    ledgerError: null,
    ledger: null,
    devicesSource: "pending",
    microphone: "",
    microphoneOptions: [],
    systemAudioDevice: "",
  };
}

export function createSettingsStore(
  initial: SettingsState = createInitialSettingsState(),
): SettingsStore {
  return createStore<SettingsState>(() => initial);
}

// --------------------------------------------------------- settings.get
/** A real settings.get result arrived: replace the engine-backed slice. */
export function applySettingsResult(store: SettingsStore, result: SettingsGetResult): void {
  store.setState({
    settingsPhase: "ready",
    settingsError: null,
    settings: result.settings,
    killSwitchEngaged: result.killSwitchEngaged,
    routing: result.routing,
    templateOptions: result.templateOptions,
  });
}

/** settings.get failed: say so honestly — never a fabricated settings object. */
export function markSettingsError(store: SettingsStore, message: string): void {
  store.setState({ settingsPhase: "error", settingsError: message });
}

/**
 * Merge a partial into the engine settings (optimistic control updates). A
 * no-op if settings have not loaded yet — a control cannot outrun the load.
 */
export function patchSettings(store: SettingsStore, partial: Partial<EngineSettings>): void {
  store.setState((state) =>
    state.settings === null ? state : { settings: { ...state.settings, ...partial } },
  );
}

/** Reflect the live kill-switch engaged state (from a fresh settings.get). */
export function setKillSwitchEngaged(store: SettingsStore, engaged: boolean): void {
  store.setState({ killSwitchEngaged: engaged });
}

// ---------------------------------------------------------- ledger.summary
export function applyLedger(store: SettingsStore, ledger: LedgerSummary): void {
  store.setState({ ledgerPhase: "ready", ledgerError: null, ledger });
}

export function markLedgerError(store: SettingsStore, message: string): void {
  store.setState({ ledgerPhase: "error", ledgerError: message });
}

// ------------------------------------------------------------- devices
export interface DeviceListingUpdate {
  readonly microphone: string;
  readonly microphoneOptions: readonly string[];
  readonly systemAudioDevice: string;
}

/** Real enumeration arrived from the engine: replace the device rows. */
export function applyDeviceListing(store: SettingsStore, listing: DeviceListingUpdate): void {
  store.setState((state) => ({
    devicesSource: "engine",
    microphoneOptions: listing.microphoneOptions,
    systemAudioDevice: listing.systemAudioDevice,
    // Keep a still-present user pick; otherwise follow the engine default.
    microphone: listing.microphoneOptions.includes(state.microphone)
      ? state.microphone
      : listing.microphone,
  }));
}

/** The engine could not answer devices.list: say so — never a fake list. */
export function markDevicesUnavailable(store: SettingsStore): void {
  store.setState({
    devicesSource: "unavailable",
    microphone: "",
    microphoneOptions: [],
    systemAudioDevice: "",
  });
}

export function setMicrophone(store: SettingsStore, device: string): void {
  store.setState((state) =>
    // Deny by default: only a device from the enumerated list is accepted.
    state.microphoneOptions.includes(device) ? { microphone: device } : state,
  );
}
