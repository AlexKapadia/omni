/**
 * REAL device enumeration over the engine's `devices.list` command —
 * retiring the mock device names from Settings.
 *
 * Parses the pinned payload FAIL-CLOSED ({devices: [{id, name, kind
 * "capture"|"render", is_default}]}), derives the Settings device fields
 * (microphone options, default microphone, the default render endpoint the
 * WASAPI loopback follows), and applies them to the settings store. An
 * offline engine or malformed payload marks devices honestly unavailable —
 * never a fabricated list.
 */
import { requestEngineReply } from "./meetings-live-repository";
import {
  applyDeviceListing,
  markDevicesUnavailable,
  type SettingsStore,
} from "./settings-store";

/** Command name pinned with the engine (device_listing_payloads.py). */
export const DEVICES_LIST_COMMAND_NAME = "devices.list";

const DEVICES_TIMEOUT_MS = 10_000;

export interface AudioDeviceEntry {
  readonly id: string;
  readonly name: string;
  readonly kind: "capture" | "render";
  readonly isDefault: boolean;
}

function isPlainObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function parseDevice(value: unknown): AudioDeviceEntry | null {
  if (!isPlainObject(value)) return null;
  const { id, name, kind, is_default } = value;
  if (typeof id !== "string" || id.length === 0) return null;
  if (typeof name !== "string" || name.length === 0) return null;
  if (kind !== "capture" && kind !== "render") return null;
  if (typeof is_default !== "boolean") return null;
  return { id, name, kind, isDefault: is_default };
}

/**
 * Validate one `devices.list` payload against the pinned engine contract.
 * Returns null on ANY deviation — one bad row poisons the whole payload.
 */
export function parseDevicesListPayload(payload: unknown): AudioDeviceEntry[] | null {
  if (!isPlainObject(payload)) return null;
  const devices = payload["devices"];
  if (!Array.isArray(devices)) return null;
  const parsed: AudioDeviceEntry[] = [];
  for (const raw of devices) {
    const device = parseDevice(raw);
    if (device === null) return null; // fail closed
    parsed.push(device);
  }
  return parsed;
}

export interface DerivedDeviceSettings {
  readonly microphone: string;
  readonly microphoneOptions: readonly string[];
  readonly systemAudioDevice: string;
}

/**
 * Settings view of the enumeration: capture devices become the microphone
 * options (default first selected); the default render endpoint names the
 * informational "system audio follows Windows" row.
 */
export function deriveDeviceSettings(devices: readonly AudioDeviceEntry[]): DerivedDeviceSettings {
  const microphones = devices.filter((d) => d.kind === "capture");
  const defaultMicrophone = microphones.find((d) => d.isDefault) ?? microphones[0];
  const defaultRender = devices.find((d) => d.kind === "render" && d.isDefault);
  return {
    microphone: defaultMicrophone?.name ?? "",
    microphoneOptions: microphones.map((d) => d.name),
    systemAudioDevice:
      defaultRender !== undefined
        ? `${defaultRender.name} (WASAPI loopback)`
        : "Default output (WASAPI loopback)",
  };
}

export type DevicesRequestFn = (
  name: string,
  payload: Record<string, unknown>,
  timeoutMs: number,
) => Promise<Record<string, unknown>>;

/**
 * Ask the engine for this machine's real devices and apply them to the
 * settings store; any failure marks the devices honestly unavailable.
 */
export async function refreshDevicesIntoSettings(
  store: SettingsStore,
  request: DevicesRequestFn = requestEngineReply,
): Promise<void> {
  try {
    const payload = await request(DEVICES_LIST_COMMAND_NAME, {}, DEVICES_TIMEOUT_MS);
    const devices = parseDevicesListPayload(payload);
    if (devices === null) {
      markDevicesUnavailable(store); // malformed = unavailable, never coerced
      return;
    }
    applyDeviceListing(store, deriveDeviceSettings(devices));
  } catch {
    markDevicesUnavailable(store); // offline engine: say so, don't invent
  }
}
