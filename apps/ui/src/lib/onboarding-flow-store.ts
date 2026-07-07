/**
 * Zustand store for the first-run wizard flow — "a two-minute ritual" (design
 * §09). Pure state + setters; the async work (folder pick, model download
 * events, Google connect, finish) lives in onboarding-flow-actions.ts.
 *
 * Everything here reflects REAL engine truth: the vault is only "configured"
 * once settings.update accepted it, and models are only "present" once the
 * engine's completed event says so (or setup.status confirms it at start).
 * Nothing is optimistically faked.
 */
import { createStore, type StoreApi } from "zustand";

export type OnboardingStep = 1 | 2 | 3 | 4;

export interface ModelFileProgress {
  readonly file: string;
  readonly receivedBytes: number;
  readonly totalBytes: number | null;
  readonly sha256Verified: boolean | null;
  readonly failedMessage: string | null;
}

export interface OnboardingFlowState {
  readonly step: OnboardingStep;
  // vault
  readonly vaultPath: string | null;
  readonly vaultConfigured: boolean;
  readonly vaultBusy: boolean;
  readonly vaultError: string | null;
  // models
  readonly modelsStarted: boolean;
  readonly modelFiles: readonly ModelFileProgress[];
  readonly modelsOk: boolean | null; // null = not finished; true/false = completed event
  // google (optional)
  readonly googleBusy: boolean;
  readonly googleConnected: boolean;
  readonly googleMessage: string | null;
  // finishing
  readonly finishing: boolean;
  readonly finishError: string | null;
}

export type OnboardingFlowStore = StoreApi<OnboardingFlowState>;

export function createOnboardingFlowState(): OnboardingFlowState {
  return {
    step: 1,
    vaultPath: null,
    vaultConfigured: false,
    vaultBusy: false,
    vaultError: null,
    modelsStarted: false,
    modelFiles: [],
    modelsOk: null,
    googleBusy: false,
    googleConnected: false,
    googleMessage: null,
    finishing: false,
    finishError: null,
  };
}

export function createOnboardingFlowStore(
  initial: OnboardingFlowState = createOnboardingFlowState(),
): OnboardingFlowStore {
  return createStore<OnboardingFlowState>(() => initial);
}

export function goToStep(store: OnboardingFlowStore, step: OnboardingStep): void {
  store.setState({ step });
}

// ------------------------------------------------------------------- vault
export function setVaultBusy(store: OnboardingFlowStore, busy: boolean): void {
  store.setState({ vaultBusy: busy, ...(busy ? { vaultError: null } : {}) });
}

export function setVaultPicked(store: OnboardingFlowStore, path: string): void {
  // A freshly-picked path is not yet configured — settings.update must accept it.
  store.setState({ vaultPath: path, vaultConfigured: false, vaultError: null });
}

export function setVaultConfigured(store: OnboardingFlowStore, path: string): void {
  store.setState({ vaultPath: path, vaultConfigured: true, vaultBusy: false, vaultError: null });
}

export function setVaultError(store: OnboardingFlowStore, message: string): void {
  store.setState({ vaultConfigured: false, vaultBusy: false, vaultError: message });
}

// ------------------------------------------------------------------ models
export function markModelsStarted(store: OnboardingFlowStore): void {
  store.setState({ modelsStarted: true, modelsOk: null });
}

/** Merge a progress frame into the per-file rows (upsert by file name). */
export function applyModelProgress(
  store: OnboardingFlowStore,
  update: Omit<ModelFileProgress, "failedMessage"> & { readonly failedMessage?: string | null },
): void {
  store.setState((state) => {
    const failedMessage = update.failedMessage ?? null;
    const next: ModelFileProgress = {
      file: update.file,
      receivedBytes: update.receivedBytes,
      totalBytes: update.totalBytes,
      sha256Verified: update.sha256Verified,
      failedMessage,
    };
    const exists = state.modelFiles.some((f) => f.file === update.file);
    const modelFiles = exists
      ? state.modelFiles.map((f) => (f.file === update.file ? next : f))
      : [...state.modelFiles, next];
    return { modelFiles };
  });
}

/** Record a failure against a file (retryable). */
export function applyModelFailed(store: OnboardingFlowStore, file: string, message: string): void {
  store.setState((state) => {
    const exists = state.modelFiles.some((f) => f.file === file);
    const failed: ModelFileProgress = {
      file,
      receivedBytes: 0,
      totalBytes: null,
      sha256Verified: null,
      failedMessage: message,
    };
    const modelFiles = exists
      ? state.modelFiles.map((f) => (f.file === file ? { ...f, failedMessage: message } : f))
      : [...state.modelFiles, failed];
    return { modelFiles, modelsOk: false };
  });
}

export function markModelsCompleted(store: OnboardingFlowStore, ok: boolean): void {
  store.setState({ modelsOk: ok, modelsStarted: false });
}

/** setup.status at wizard start says models are already present — skip download. */
export function markModelsAlreadyPresent(store: OnboardingFlowStore): void {
  store.setState({ modelsOk: true });
}

// ------------------------------------------------------------------ google
export function setGoogleBusy(store: OnboardingFlowStore, busy: boolean): void {
  store.setState({ googleBusy: busy });
}

export function setGoogleResult(store: OnboardingFlowStore, connected: boolean, message: string): void {
  store.setState({ googleBusy: false, googleConnected: connected, googleMessage: message });
}

// ------------------------------------------------------------------ finish
export function setFinishing(store: OnboardingFlowStore, finishing: boolean): void {
  store.setState({ finishing, ...(finishing ? { finishError: null } : {}) });
}

export function setFinishError(store: OnboardingFlowStore, message: string): void {
  store.setState({ finishing: false, finishError: message });
}

/** True once the completed event reported success (or models were present). */
export function modelsPresent(state: OnboardingFlowState): boolean {
  return state.modelsOk === true;
}
