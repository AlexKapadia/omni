/**
 * useMicLevelPercent: when a PortAudio-style mic name is provided, match a
 * browser audioinput by label and request that deviceId; otherwise fall back.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, renderHook, waitFor } from "@testing-library/react";
import { useMicLevelPercent } from "./use-mic-level-percent";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("useMicLevelPercent device matching", () => {
  beforeEach(() => {
    const track = { stop: vi.fn() };
    const stream = {
      getTracks: () => [track],
    } as unknown as MediaStream;

    const getUserMedia = vi.fn(async () => stream);
    const enumerateDevices = vi.fn(async () => [
      { kind: "audioinput", deviceId: "browser-usb", label: "USB Mic (Realtek)" },
      { kind: "audioinput", deviceId: "browser-default", label: "Default Microphone" },
    ]);

    Object.defineProperty(navigator, "mediaDevices", {
      configurable: true,
      value: { getUserMedia, enumerateDevices },
    });

    // Minimal AudioContext stub so the meter path does not throw in jsdom.
    class FakeAnalyser {
      fftSize = 256;
      frequencyBinCount = 128;
      connect() {}
      getByteFrequencyData(data: Uint8Array) {
        data.fill(0);
      }
    }
    class FakeContext {
      createMediaStreamSource() {
        return { connect() {} };
      }
      createAnalyser() {
        return new FakeAnalyser();
      }
      close() {
        return Promise.resolve();
      }
    }
    vi.stubGlobal("AudioContext", FakeContext);
    vi.stubGlobal("requestAnimationFrame", (cb: FrameRequestCallback) => {
      cb(0);
      return 1;
    });
    vi.stubGlobal("cancelAnimationFrame", () => {});
  });

  it("requests the browser device whose label matches the selected mic name", async () => {
    renderHook(() => useMicLevelPercent(true, "9:USB Mic"));
    await waitFor(() => {
      expect(navigator.mediaDevices.getUserMedia).toHaveBeenCalledWith({
        audio: { deviceId: { exact: "browser-usb" } },
      });
    });
  });

  it("falls back to default audio when no label matches", async () => {
    renderHook(() => useMicLevelPercent(true, "2:Unknown Device"));
    await waitFor(() => {
      expect(navigator.mediaDevices.getUserMedia).toHaveBeenCalledWith({ audio: true });
    });
  });
});
