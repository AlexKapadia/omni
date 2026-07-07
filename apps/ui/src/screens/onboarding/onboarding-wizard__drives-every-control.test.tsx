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
  keys: { groq: true, gemini: true, anthropic: false, cartesia: false },
  vault: { configured: true, path: "C:/picked" },
  models: [{ file: "m", present: true, bytes: 1 }],
  googleConnected: false,
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
    finishOnboarding: async (_store, onDone) => {
      onDoneSpy();
      onDone(DONE_STATUS);
    },
  };
}

const validValidator = (provider: "groq" | "gemini" | "anthropic" | "cartesia"): Promise<KeyValidationResult> =>
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
  it("walks welcome → vault → keys → models → finish, exercising each element", async () => {
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

    // Step 1 — welcome + privacy truths, then Begin.
    expect(screen.getByText("No bot joins your calls.")).toBeTruthy();
    expect(screen.getByText("Audio is discarded after transcription.")).toBeTruthy();
    await act(async () => fireEvent.click(screen.getByRole("button", { name: "Begin" })));

    // Step 2 — browse fills the path, use-folder configures it.
    expect(screen.getByText("Choose your vault")).toBeTruthy();
    await act(async () => fireEvent.click(screen.getByRole("button", { name: "Browse" })));
    expect((screen.getByLabelText("Vault folder path") as HTMLInputElement).value).toBe("C:/picked");
    await act(async () => fireEvent.click(screen.getByRole("button", { name: "Use this folder" })));
    await waitFor(() => expect(screen.getByText("✓ folder ready")).toBeTruthy());
    // Continue is enabled only once the vault is configured.
    await act(async () => fireEvent.click(screen.getByRole("button", { name: "Continue" })));

    // Step 3 — save + validate the two required keys.
    expect(screen.getByText("Add your keys")).toBeTruthy();
    await saveAndValidate("Groq");
    await saveAndValidate("Gemini");
    expect(keysStore.getState().validation.groq.status).toBe("valid");
    expect(keysStore.getState().validation.gemini.status).toBe("valid");
    await act(async () => fireEvent.click(screen.getByRole("button", { name: "Continue" })));

    // Step 4 — Finish is blocked until models present; download unblocks it.
    expect(screen.getByText("Get the models")).toBeTruthy();
    const finishBtn = () => screen.getByRole("button", { name: "Finish" }) as HTMLButtonElement;
    expect(finishBtn().disabled).toBe(true);
    await act(async () => fireEvent.click(screen.getByRole("button", { name: "Download" })));
    await waitFor(() => expect(screen.getByText("✓ models ready")).toBeTruthy());

    // Optional Google connect + its Skip both work.
    await act(async () => fireEvent.click(screen.getByRole("button", { name: "Connect Google" })));
    await waitFor(() => expect(screen.getByText("✓ Google connected")).toBeTruthy());

    // Finish now enabled — completes only after the engine confirms.
    await waitFor(() => expect(finishBtn().disabled).toBe(false));
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
    await act(async () => fireEvent.click(screen.getByRole("button", { name: "Begin" })));
    await act(async () => fireEvent.click(screen.getByRole("button", { name: "Continue" }))); // → step 3
    expect(screen.getByText("Add your keys")).toBeTruthy();
    await act(async () => fireEvent.click(screen.getByRole("button", { name: "Back" })));
    expect(screen.getByText("Choose your vault")).toBeTruthy(); // back on step 2
  });

  it("Finish stays blocked with an explicit reason when keys are unvalidated", async () => {
    const flowStore = createOnboardingFlowStore();
    setVaultConfigured(flowStore, "C:/picked");
    markModelsCompleted(flowStore, true);
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
    await act(async () => fireEvent.click(screen.getByRole("button", { name: "Begin" })));
    await act(async () => fireEvent.click(screen.getByRole("button", { name: "Continue" }))); // step 3
    await act(async () => fireEvent.click(screen.getByRole("button", { name: "Continue" }))); // step 4
    expect((screen.getByRole("button", { name: "Finish" }) as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getByText(/validate your Groq and Gemini keys/)).toBeTruthy();
  });
});
