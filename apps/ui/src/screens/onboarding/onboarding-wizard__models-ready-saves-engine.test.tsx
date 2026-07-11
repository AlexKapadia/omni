/**
 * When models are already present, Continue must still persist engine/summary
 * selection before advancing (same save as Download & continue).
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

describe("onboarding modelsReady Continue saves engine selection", () => {
  it("calls saveEngineSelection before advancing when models are already ready", async () => {
    const flowStore: OnboardingFlowStore = createOnboardingFlowStore();
    markModelsCompleted(flowStore, true);
    flowStore.setState({ step: 5 });
    const saveEngineSelection = vi.fn(async () => undefined);
    const actions: OnboardingActions = {
      initFromSetupStatus: async () => undefined,
      chooseVaultFolder: async (store) => setVaultPicked(store, "C:/picked"),
      configureVault: async (store, path) => {
        setVaultConfigured(store, path);
        return true;
      },
      subscribeModelDownload: () => () => undefined,
      beginModelDownload: async () => undefined,
      subscribeGoogleConnect: () => () => undefined,
      beginGoogleConnect: async (store) => setGoogleResult(store, true, "Connected."),
      skipGoogleConnect: () => undefined,
      finishOnboarding: async (_store, onDone) => onDone(DONE_STATUS),
      enrollSpeaker: async () => undefined,
      saveEngineSelection,
    };

    render(
      <OnboardingWizard
        onComplete={() => undefined}
        flowStore={flowStore}
        keysStore={createApiKeysStore()}
        vault={{ persistKey: () => Promise.resolve() }}
        validator={(provider): Promise<KeyValidationResult> =>
          Promise.resolve({ provider, valid: true, message: "ok", latencyMs: 1 })
        }
        actions={actions}
      />,
    );

    expect(screen.getByRole("button", { name: "Continue" })).toBeTruthy();
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Continue" }));
    });
    await waitFor(() => expect(saveEngineSelection).toHaveBeenCalled());
    expect(saveEngineSelection).toHaveBeenCalledWith(
      expect.any(String),
      expect.any(String),
    );
  });
});
