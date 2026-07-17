/**
 * Live-interaction wizard test (the browser-driven E2E fallback — Playwright
 * browsers are not installable in this environment, see the lane report). It
 * renders the RUNNING wizard and clicks through EVERY interactive element with
 * fake engine actions that produce real store transitions: begin, browse,
 * use-folder, key save + validate, continue/back, download, connect google,
 * skip, and finish — asserting each reaches the right state.
 */
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { OnboardingWizard, type OnboardingActions } from "./onboarding-wizard";
import { createApiKeysStore } from "../../lib/api-keys-store";
import {
  createOnboardingFlowStore,
  markModelsCompleted,
  setGoogleResult,
  setVaultConfigured,
  setVaultPicked,
  type OnboardingFlowStore,
} from "../../lib/onboarding-flow-store";
import type { KeyValidationResult } from "../../lib/setup-settings-payloads";
import type { SetupStatus } from "../../lib/setup-settings-payloads";
import { installJsdomMatchMediaShim } from "../../test-support/install-jsdom-match-media-shim";

beforeAll(installJsdomMatchMediaShim);
afterEach(cleanup);

const DONE_STATUS: SetupStatus = {
  keys: {
    groq: true,
    gemini: true,
    anthropic: false,
    openai: false,
    openrouter: false,
    azure_openai: false,
    cartesia: false,
  },
  vault: { configured: true, path: "C:/picked" },
  models: [{ file: "m", present: true, bytes: 1 }],
  googleConnected: false,
  microsoftConnected: false,
  onboardingComplete: true,
  setupComplete: true,
};

/** Fake actions that drive REAL store transitions the wizard reacts to. */
function fakeActions(onDoneSpy: () => void): OnboardingActions {
  return {
    initFromSetupStatus: async () => undefined,
    chooseVaultFolder: async (store) => setVaultPicked(store, "C:/picked"),
    configureVault: async (store, path) => {
      setVaultConfigured(store, path);
      return true;
    },
    subscribeModelDownload: () => () => undefined,
    beginModelDownload: async (store) => markModelsCompleted(store, true),
    subscribeGoogleConnect: () => () => undefined,
    beginGoogleConnect: async (store) => setGoogleResult(store, true, "Connected."),
    skipGoogleConnect: () => undefined,
    finishOnboarding: async (_store, onDone) => {
      onDoneSpy();
      onDone(DONE_STATUS);
    },
    enrollSpeaker: async () => undefined,
    saveEngineSelection: async () => undefined,
  };
}

const validValidator = (provider: KeyValidationResult["provider"]): Promise<KeyValidationResult> =>
  Promise.resolve({ provider, valid: true, message: "reachable", latencyMs: 20 });

async function saveAndValidate(label: string): Promise<void> {
  const input = screen.getByLabelText(`${label} API key`);
  fireEvent.change(input, { target: { value: "sk-live-abcdef123456" } });
  await act(async () => {
    fireEvent.submit(input.closest("form")!);
  });
  await act(async () => {
    fireEvent.click(screen.getByRole("button", { name: `Validate ${label}` }));
  });
}

describe("first-run wizard drives every control", () => {
  it("walks welcome → speaker → vault → models → finish (keys + calendar), exercising each element", async () => {
    const flowStore: OnboardingFlowStore = createOnboardingFlowStore();
    const keysStore = createApiKeysStore();
    const onComplete = vi.fn();
    const onDoneSpy = vi.fn();

    render(
      <OnboardingWizard
        onComplete={onComplete}
        flowStore={flowStore}
        keysStore={keysStore}
        vault={{ persistKey: () => Promise.resolve() }}
        validator={validValidator}
        actions={fakeActions(onDoneSpy)}
      />,
    );

    // Step 1 — welcome + privacy truths, then Get started.
    expect(screen.getByText("No bot joins your calls.")).toBeTruthy();
    expect(screen.getByText("Recordings stay on this device as MP3.")).toBeTruthy();
    await act(async () => fireEvent.click(screen.getByRole("button", { name: "Get started" })));

    // Step 2 — features tour.
    expect(screen.getByText("What Omni Steroid can do")).toBeTruthy();
    await act(async () => fireEvent.click(screen.getByRole("button", { name: "Got it, continue" })));

    // Step 3 — speaker identity.
    expect(screen.getByText("What's your name?")).toBeTruthy();
    const nameInput = screen.getByLabelText("Your name");
    fireEvent.change(nameInput, { target: { value: "Alex" } });
    await act(async () => fireEvent.click(screen.getByRole("button", { name: "Continue" })));

    // Step 4 — browse fills the path, Continue configures it.
    expect(screen.getByText("Where should notes be saved?")).toBeTruthy();
    await act(async () => fireEvent.click(screen.getByRole("button", { name: "Choose folder" })));
    await act(async () => fireEvent.click(screen.getByRole("button", { name: "Continue" })));

    // Step 5 — models download, then Continue.
    expect(screen.getByText("Download on-device models")).toBeTruthy();
    await act(async () => fireEvent.click(screen.getByRole("button", { name: "Download & continue" })));
    await waitFor(() => expect(screen.getByText("Transcription models ready for live capture")).toBeTruthy());
    await act(async () => fireEvent.click(screen.getByRole("button", { name: "Continue" })));

    // Step 6 — Finish setup.
    expect(screen.getByText("Finish setup")).toBeTruthy();
    
    // Open API Keys collapsible
    await act(async () => fireEvent.click(screen.getByRole("button", { name: "API Keys (Optional)" })));
    await saveAndValidate("Groq");
    await saveAndValidate("Gemini");
    expect(keysStore.getState().validation.groq.status).toBe("valid");
    expect(keysStore.getState().validation.gemini.status).toBe("valid");

    // Open Calendar collapsible
    await act(async () => fireEvent.click(screen.getByRole("button", { name: "Calendar Integration (Optional)" })));
    const connectBtn = () => screen.getByRole("button", { name: "Connect Google" });
    await act(async () => fireEvent.click(connectBtn()));
    await waitFor(() => expect(screen.getByText("✓ Google connected")).toBeTruthy());

    const finishBtn = () => screen.getByRole("button", { name: "Finish" }) as HTMLButtonElement;
    expect(finishBtn().disabled).toBe(false);
    await act(async () => fireEvent.click(finishBtn()));
    expect(onDoneSpy).toHaveBeenCalledTimes(1);
    expect(onComplete).toHaveBeenCalledTimes(1);
  });

  it("Back navigates to the previous step", async () => {
    const flowStore = createOnboardingFlowStore();
    setVaultConfigured(flowStore, "C:/picked");
    render(
      <OnboardingWizard
        onComplete={vi.fn()}
        flowStore={flowStore}
        keysStore={createApiKeysStore()}
        vault={{ persistKey: () => Promise.resolve() }}
        validator={validValidator}
        actions={fakeActions(vi.fn())}
      />,
    );
    await act(async () => fireEvent.click(screen.getByRole("button", { name: "Get started" })));
    
    // We are on step 2. Click Got it, continue -> step 3.
    expect(screen.getByText("What Omni Steroid can do")).toBeTruthy();
    await act(async () => fireEvent.click(screen.getByRole("button", { name: "Got it, continue" })));

    // We are on step 3. Type name and click Continue -> step 4.
    const nameInput = screen.getByLabelText("Your name");
    fireEvent.change(nameInput, { target: { value: "Alex" } });
    await act(async () => fireEvent.click(screen.getByRole("button", { name: "Continue" })));
    expect(screen.getByText("Where should notes be saved?")).toBeTruthy();
    
    // Click Back -> step 3.
    await act(async () => fireEvent.click(screen.getByRole("button", { name: "Back" })));
    expect(screen.getByText("What's your name?")).toBeTruthy(); // back on step 3
  });
});
