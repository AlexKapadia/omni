/**
 * Enrollment WAV must advertise the AudioContext's real sample rate.
 */
import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { float32ToWavBase64, recordVoiceSampleWavBase64 } from "./record-voice-sample";

describe("float32ToWavBase64", () => {
  it("writes the provided sampleRate into the WAV header", () => {
    const samples = new Float32Array([0, 0.5, -0.5]);
    const b64 = float32ToWavBase64(samples, 48_000);
    const bytes = Uint8Array.from(atob(b64), (c) => c.charCodeAt(0));
    const view = new DataView(bytes.buffer);
    expect(view.getUint32(24, true)).toBe(48_000);
    expect(view.getUint32(28, true)).toBe(48_000 * 2);
  });
});

describe("recordVoiceSampleWavBase64", () => {
  const originalAudioContext = globalThis.AudioContext;
  const originalMediaDevices = navigator.mediaDevices;

  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
    globalThis.AudioContext = originalAudioContext;
    Object.defineProperty(navigator, "mediaDevices", {
      configurable: true,
      value: originalMediaDevices,
    });
  });

  it("uses AudioContext.sampleRate even when the browser ignores the 16k hint", async () => {
    const stop = vi.fn();
    Object.defineProperty(navigator, "mediaDevices", {
      configurable: true,
      value: {
        getUserMedia: vi.fn().mockResolvedValue({
          getTracks: () => [{ stop }],
        }),
      },
    });

    class FakeAudioContext {
      sampleRate = 44_100;
      destination = {};
      createMediaStreamSource() {
        return { connect: vi.fn(), disconnect: vi.fn() };
      }
      createScriptProcessor() {
        return {
          connect: vi.fn(),
          disconnect: vi.fn(),
          onaudioprocess: null as ((event: { inputBuffer: { getChannelData: () => Float32Array } }) => void) | null,
        };
      }
      close = vi.fn().mockResolvedValue(undefined);
    }
    globalThis.AudioContext = FakeAudioContext as unknown as typeof AudioContext;

    const pending = recordVoiceSampleWavBase64(0.01);
    await vi.runAllTimersAsync();
    const b64 = await pending;
    const bytes = Uint8Array.from(atob(b64), (c) => c.charCodeAt(0));
    const view = new DataView(bytes.buffer);
    expect(view.getUint32(24, true)).toBe(44_100);
  });
});
