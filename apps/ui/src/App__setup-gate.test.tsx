/**
 * App boot-gate tests: setup.status decides first-run onboarding vs the main
 * shell. A returning user (complete) sees the shell; an incomplete setup sees
 * the wizard; a transient status error does not trap the user in onboarding.
 */
import { afterEach, beforeAll, describe, expect, it } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import App from "./App";
import type { SetupStatus } from "./lib/setup-settings-payloads";
import { installJsdomMatchMediaShim } from "./test-support/install-jsdom-match-media-shim";

/** Minimal WebSocket stub so startLiveEngineConnection never throws in jsdom. */
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
  keys: { groq: true, gemini: true, anthropic: true, cartesia: true },
  vault: { configured: true, path: "C:/vault" },
  models: [{ file: "m", present: true, bytes: 1 }],
  googleConnected: true,
  onboardingComplete: true,
  setupComplete: true,
};

const incomplete: SetupStatus = { ...complete, onboardingComplete: false, setupComplete: false };

describe("App setup gate", () => {
  it("renders the first-run wizard when setup is incomplete", async () => {
    render(<App checkStatus={() => Promise.resolve(incomplete)} />);
    await waitFor(() => expect(screen.getByText("1 / 5")).toBeTruthy());
    expect(screen.getByRole("button", { name: "Begin" })).toBeTruthy();
  });

  it("renders the main shell when setup is complete", async () => {
    render(<App checkStatus={() => Promise.resolve(complete)} />);
    // The nav rail is a main-shell fixture, not present in the wizard.
    await waitFor(() => expect(screen.queryByText("1 / 5")).toBeNull());
    expect(screen.getByRole("navigation")).toBeTruthy();
  });

  it("does not trap the user in onboarding on a transient status error", async () => {
    // Zero retry budget: the first rejection is past the deadline, so the app
    // gives up and shows the shell immediately (production default is 10 s).
    render(
      <App
        checkStatus={() => Promise.reject(new Error("engine starting"))}
        bootRetryBudgetMs={0}
      />,
    );
    await waitFor(() => expect(screen.getByRole("navigation")).toBeTruthy());
    expect(screen.queryByText("1 / 5")).toBeNull();
  });
});
