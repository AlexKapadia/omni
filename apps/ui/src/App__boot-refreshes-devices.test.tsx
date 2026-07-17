/**
 * App boot refreshes devices into the settings store (not only Settings screen).
 */
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import { cleanup, render, waitFor } from "@testing-library/react";
import type { SetupStatus } from "./lib/setup-settings-payloads";
import { installJsdomMatchMediaShim } from "./test-support/install-jsdom-match-media-shim";

const refreshDevices = vi.fn(async (..._args: unknown[]) => undefined);
const loadSettings = vi.fn(async (..._args: unknown[]) => undefined);

vi.mock("./lib/engine-devices", async (importOriginal) => {
  const actual = await importOriginal<typeof import("./lib/engine-devices")>();
  return { ...actual, refreshDevicesIntoSettings: (...args: unknown[]) => refreshDevices(...args) };
});

vi.mock("./lib/settings-actions", async (importOriginal) => {
  const actual = await importOriginal<typeof import("./lib/settings-actions")>();
  return { ...actual, loadSettings: (...args: unknown[]) => loadSettings(...args) };
});

import App from "./App";

class StubWebSocket {
  static readonly OPEN = 1;
  onopen: (() => void) | null = null;
  onmessage: ((e: { data: unknown }) => void) | null = null;
  onclose: (() => void) | null = null;
  onerror: (() => void) | null = null;
  readyState = 0;
  send(): void {}
  close(): void {}
}

beforeAll(() => {
  installJsdomMatchMediaShim();
  (globalThis as unknown as { WebSocket: unknown }).WebSocket = StubWebSocket;
});
afterEach(() => {
  cleanup();
  refreshDevices.mockClear();
  loadSettings.mockClear();
});

const complete: SetupStatus = {
  keys: {
    groq: true,
    gemini: true,
    anthropic: true,
    openai: false,
    openrouter: false,
    azure_openai: false,
    cartesia: true,
  },
  vault: { configured: true, path: "C:/vault" },
  models: [{ file: "m", present: true, bytes: 1 }],
  googleConnected: true,
  microsoftConnected: false,
  onboardingComplete: true,
  setupComplete: true,
};

describe("App boot device refresh", () => {
  it("loads settings and refreshes devices when the main shell mounts", async () => {
    render(<App checkStatus={() => Promise.resolve(complete)} />);
    await waitFor(() => expect(loadSettings).toHaveBeenCalled());
    await waitFor(() => expect(refreshDevices).toHaveBeenCalled());
  });
});
