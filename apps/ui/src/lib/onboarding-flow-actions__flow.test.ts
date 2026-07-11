/**
 * onboarding-flow-actions tests: the vault is configured only when the engine
 * accepts it (create_vault_dir passed through), a rejection surfaces the
 * engine message verbatim, model progress is driven by REAL events, a failed
 * start becomes retryable, and finish waits for the engine to confirm.
 */
import { describe, expect, it, vi } from "vitest";
import {
  beginModelDownload,
  configureVault,
  finishOnboarding,
  initFromSetupStatus,
  subscribeModelDownload,
} from "./onboarding-flow-actions";
import {
  createOnboardingFlowStore,
  modelsPresent,
} from "./onboarding-flow-store";
import { createApiKeysStore } from "./api-keys-store";
import type { EngineSocketTransport } from "./setup-settings-transport";
import { PROTOCOL_VERSION } from "./protocol";
import type { SetupStatus } from "./setup-settings-payloads";

function fakeSocket() {
  let listener: ((data: unknown) => void) | null = null;
  const transport: EngineSocketTransport = {
    sendEnvelope: () => true,
    subscribeFrames: (l) => {
      listener = l;
      return () => {
        listener = null;
      };
    },
  };
  const evt = (name: string, payload: Record<string, unknown>) =>
    listener?.({ v: PROTOCOL_VERSION, kind: "event", name, id: "e", payload });
  return { transport, evt };
}

describe("configureVault", () => {
  it("configures the vault and passes create_vault_dir through", async () => {
    const store = createOnboardingFlowStore();
    const update = vi.fn(async () => ({}));
    const ok = await configureVault(store, "  C:/new vault  ", true, update);
    expect(ok).toBe(true);
    expect(update).toHaveBeenCalledWith({ vault_dir: "C:/new vault" }, true);
    expect(store.getState().vaultConfigured).toBe(true);
    expect(store.getState().vaultPath).toBe("C:/new vault");
  });

  it("surfaces the engine rejection verbatim and stays unconfigured", async () => {
    const store = createOnboardingFlowStore();
    const ok = await configureVault(store, "C:/ro", false, async () => {
      throw new Error("folder is not writable");
    });
    expect(ok).toBe(false);
    expect(store.getState().vaultConfigured).toBe(false);
    expect(store.getState().vaultError).toBe("folder is not writable");
  });

  it("refuses an empty path without calling the engine", async () => {
    const store = createOnboardingFlowStore();
    const update = vi.fn(async () => ({}));
    expect(await configureVault(store, "   ", false, update)).toBe(false);
    expect(update).not.toHaveBeenCalled();
  });
});

describe("model download from real events", () => {
  it("fills per-file progress and marks present on a successful completion", async () => {
    const store = createOnboardingFlowStore();
    const s = fakeSocket();
    subscribeModelDownload(store, s.transport);
    await beginModelDownload(store, async () => undefined);
    expect(store.getState().modelsStarted).toBe(true);
    s.evt("models.download.progress", { file: "parakeet.bin", received_bytes: 50, total_bytes: 100, sha256_verified: null });
    s.evt("models.download.progress", { file: "parakeet.bin", received_bytes: 100, total_bytes: 100, sha256_verified: true });
    s.evt("models.download.completed", { ok: true, files: ["parakeet.bin"] });
    const state = store.getState();
    expect(state.modelFiles).toHaveLength(1);
    expect(state.modelFiles[0]!.sha256Verified).toBe(true);
    expect(modelsPresent(state)).toBe(true);
  });

  it("a failed start is retryable (marks failed, not started)", async () => {
    const store = createOnboardingFlowStore();
    await beginModelDownload(store, async () => {
      throw new Error("no network");
    });
    expect(store.getState().modelsOk).toBe(false);
    expect(store.getState().modelFiles.some((f) => f.failedMessage === "no network")).toBe(true);
    expect(store.getState().modelsStarted).toBe(false);
  });

  it("a per-file failed event records the engine message", async () => {
    const store = createOnboardingFlowStore();
    const s = fakeSocket();
    subscribeModelDownload(store, s.transport);
    s.evt("models.download.failed", { file: "bge.onnx", message: "checksum mismatch" });
    expect(store.getState().modelFiles[0]).toMatchObject({ file: "bge.onnx", failedMessage: "checksum mismatch" });
  });
});

const STATUS: SetupStatus = {
  keys: {
    groq: true,
    gemini: true,
    anthropic: false,
    openai: false,
    openrouter: false,
    azure_openai: false,
    cartesia: true,
  },
  vault: { configured: true, path: "C:/vault" },
  models: [{ file: "m", present: true, bytes: 1 }],
  googleConnected: true,
  microsoftConnected: false,
  onboardingComplete: false,
  setupComplete: false,
};

describe("initFromSetupStatus", () => {
  it("pre-fills configured vault, present models and google from real status", async () => {
    const store = createOnboardingFlowStore();
    const keysStore = createApiKeysStore();
    await initFromSetupStatus(store, async () => STATUS, keysStore);
    const state = store.getState();
    expect(state.vaultConfigured).toBe(true);
    expect(state.vaultPath).toBe("C:/vault");
    expect(modelsPresent(state)).toBe(true);
    expect(state.googleConnected).toBe(true);
    expect(keysStore.getState().keys.groq.saved).toBe(true);
    expect(keysStore.getState().keys.cartesia.saved).toBe(true);
    expect(keysStore.getState().keys.cartesia.lastFour).toBe("••••");
  });

  it("proceeds from blank when status cannot be read (fresh install)", async () => {
    const store = createOnboardingFlowStore();
    await initFromSetupStatus(store, async () => {
      throw new Error("starting");
    });
    expect(store.getState().vaultConfigured).toBe(false);
  });
});

describe("finishOnboarding", () => {
  it("calls onDone only after the engine confirms", async () => {
    const store = createOnboardingFlowStore();
    const onDone = vi.fn();
    await finishOnboarding(store, onDone, {
      update: async () => ({}),
      getStatus: async () => ({ ...STATUS, onboardingComplete: true, setupComplete: true }),
    });
    expect(onDone).toHaveBeenCalledTimes(1);
    expect(store.getState().finishing).toBe(false);
  });

  it("surfaces a finish error and does not call onDone", async () => {
    const store = createOnboardingFlowStore();
    const onDone = vi.fn();
    await finishOnboarding(store, onDone, {
      update: async () => {
        throw new Error("could not persist");
      },
    });
    expect(onDone).not.toHaveBeenCalled();
    expect(store.getState().finishError).toBe("could not persist");
  });
});
