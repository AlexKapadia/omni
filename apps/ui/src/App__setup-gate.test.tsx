/**
 * App boot-gate tests: setup.status decides first-run onboarding vs the main
 * shell. A returning user (complete) sees the shell; an incomplete setup sees
 * the wizard; a persistent status error shows an offline retry screen — never
 * skips first-run by inventing a completed setup.
 */
import { afterEach, beforeAll, describe, expect, it } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import App from "./App";
import type { SetupStatus } from "./lib/setup-settings-payloads";
import { installJsdomMatchMediaShim } from "./test-support/install-jsdom-match-media-shim";

/** Minimal WebSocket stub so startLiveEngine connection never throws in jsdom. */
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
afterEach(cleanup);

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

const incomplete: SetupStatus = { ...complete, onboardingComplete: false, setupComplete: false };

describe("App setup gate", () => {
  it("renders the first-run wizard when setup is incomplete", async () => {
    render(<App checkStatus={() => Promise.resolve(incomplete)} />);
    await waitFor(() => expect(screen.getByLabelText("Onboarding step 1 of 6")).toBeTruthy());
    expect(screen.getByRole("button", { name: "Get started" })).toBeTruthy();
  });

  it("renders the main shell when setup is complete", async () => {
    render(<App checkStatus={() => Promise.resolve(complete)} />);
    // The nav rail is a main-shell fixture, not present in the wizard.
    await waitFor(() => expect(screen.queryByLabelText("Onboarding step 1 of 6")).toBeNull());
    expect(screen.getByRole("navigation")).toBeTruthy();
  });

  it("shows an offline retry screen when the engine never answers (does not skip onboarding)", async () => {
    render(
      <App
        checkStatus={() => Promise.reject(new Error("engine starting"))}
        bootRetryBudgetMs={0}
      />,
    );
    await waitFor(() => expect(screen.getByLabelText("Engine offline")).toBeTruthy());
    expect(screen.getByRole("button", { name: "Retry connection" })).toBeTruthy();
    expect(screen.queryByRole("navigation")).toBeNull();
    expect(screen.queryByLabelText("Onboarding step 1 of 6")).toBeNull();
  });
});
