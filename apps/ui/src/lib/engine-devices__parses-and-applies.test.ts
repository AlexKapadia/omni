/**
 * Real-device flow tests: fail-closed devices.list parsing, the Settings
 * derivation (capture -> microphone options, default render -> the loopback
 * row), and refresh honesty — engine offline or a malformed payload marks
 * devices unavailable, never a fabricated list.
 */
import { describe, expect, it } from "vitest";
import {
  deriveDeviceSettings,
  parseDevicesListPayload,
  refreshDevicesIntoSettings,
} from "./engine-devices";
import { createInitialSettingsState, createSettingsStore } from "./settings-store";

const WIRE_DEVICES = [
  { id: "3:Headset Microphone", name: "Headset Microphone", kind: "capture", is_default: true },
  { id: "9:USB Mic", name: "USB Mic", kind: "capture", is_default: false },
  { id: "7:Speakers [Loopback]", name: "Speakers", kind: "render", is_default: true },
  { id: "8:Monitor [Loopback]", name: "Monitor Audio", kind: "render", is_default: false },
];

describe("parseDevicesListPayload (fail closed)", () => {
  it("accepts the pinned engine shape", () => {
    const parsed = parseDevicesListPayload({ devices: WIRE_DEVICES });
    expect(parsed).toHaveLength(4);
    expect(parsed![0]).toEqual({
      id: "3:Headset Microphone",
      name: "Headset Microphone",
      kind: "capture",
      isDefault: true,
    });
  });

  it("accepts an honestly empty machine (no devices)", () => {
    expect(parseDevicesListPayload({ devices: [] })).toEqual([]);
  });

  it.each([
    ["not an object", null],
    ["devices missing", {}],
    ["devices not a list", { devices: "many" }],
    ["one row with a bad kind poisons the payload", { devices: [{ ...WIRE_DEVICES[0], kind: "loopback" }] }],
    ["one row with a numeric id poisons the payload", { devices: [WIRE_DEVICES[0], { ...WIRE_DEVICES[1], id: 9 }] }],
    ["one row missing is_default poisons the payload", { devices: [{ id: "1:x", name: "x", kind: "capture" }] }],
  ])("rejects %s", (_label, payload) => {
    expect(parseDevicesListPayload(payload)).toBeNull();
  });
});

describe("deriveDeviceSettings", () => {
  it("derives id-keyed options from capture devices and the loopback row from the default render", () => {
    const parsed = parseDevicesListPayload({ devices: WIRE_DEVICES })!;
    expect(deriveDeviceSettings(parsed)).toEqual({
      microphone: "3:Headset Microphone", // default capture device id
      microphoneOptions: [
        { id: "3:Headset Microphone", name: "Headset Microphone" },
        { id: "9:USB Mic", name: "USB Mic" },
      ],
      systemAudioDevice: "Speakers (WASAPI loopback)", // default render only
    });
  });

  it("degrades honestly with no default flags and no render devices", () => {
    const parsed = parseDevicesListPayload({
      devices: [{ id: "9:USB Mic", name: "USB Mic", kind: "capture", is_default: false }],
    })!;
    expect(deriveDeviceSettings(parsed)).toEqual({
      microphone: "9:USB Mic", // first capture stands in when none is default
      microphoneOptions: [{ id: "9:USB Mic", name: "USB Mic" }],
      systemAudioDevice: "Default output (WASAPI loopback)",
    });
  });
});

describe("refreshDevicesIntoSettings", () => {
  it("applies a real listing and keeps a still-valid user pick by id", async () => {
    const store = createSettingsStore({
      ...createInitialSettingsState(),
      devicesSource: "engine",
      microphone: "9:USB Mic", // the user's previous choice (device id)
      microphoneOptions: [{ id: "9:USB Mic", name: "USB Mic" }],
    });
    await refreshDevicesIntoSettings(store, async () => ({ devices: WIRE_DEVICES }));
    const state = store.getState();
    expect(state.devicesSource).toBe("engine");
    expect(state.microphoneOptions).toEqual([
      { id: "3:Headset Microphone", name: "Headset Microphone" },
      { id: "9:USB Mic", name: "USB Mic" },
    ]);
    expect(state.microphone).toBe("9:USB Mic"); // still present -> preserved
    expect(state.systemAudioDevice).toBe("Speakers (WASAPI loopback)");
  });

  it("an offline engine marks devices unavailable, never a fake list", async () => {
    const store = createSettingsStore(createInitialSettingsState());
    await refreshDevicesIntoSettings(store, async () => {
      throw new Error("The engine is offline.");
    });
    const state = store.getState();
    expect(state.devicesSource).toBe("unavailable");
    expect(state.microphoneOptions).toEqual([]);
    expect(state.microphone).toBe("");
  });

  it("a malformed payload marks devices unavailable (fail closed)", async () => {
    const store = createSettingsStore(createInitialSettingsState());
    await refreshDevicesIntoSettings(store, async () => ({ devices: "corrupt" }));
    expect(store.getState().devicesSource).toBe("unavailable");
  });
});
