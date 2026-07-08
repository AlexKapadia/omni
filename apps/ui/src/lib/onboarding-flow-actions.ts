/**
 * Async orchestration for the first-run wizard: enumerate real setup status,
 * configure the vault, run the model download from real progress events,
 * connect Google, and finish. Kept apart from the pure flow store so each
 * action is testable with fakes and no socket.
 *
 * Honesty invariant: nothing here fabricates success — the vault is configured
 * only when settings.update accepts it, models are "present" only when the
 * engine's completed event says ok, and finish re-reads setup.status.
 */
import {
  applyModelFailed,
  applyModelProgress,
  markModelsAlreadyPresent,
  markModelsCompleted,
  markModelsStarted,
  markGoogleSkipped,
  setFinishError,
  setFinishing,
  setGoogleBusy,
  setGoogleResult,
  setVaultBusy,
  setVaultConfigured,
  setVaultError,
  setVaultPicked,
  type OnboardingFlowStore,
} from "./onboarding-flow-store";
import { pickVaultDirectory } from "./pick-vault-directory";
import {
  connectGoogle,
  getSetupStatus,
  startModelsDownload,
  updateSettings,
} from "./setup-settings-repository";
import {
  subscribeToGoogleConnect,
  subscribeToModelsDownload,
  type EngineSocketTransport,
} from "./setup-settings-transport";
import type { SetupStatus } from "./setup-settings-payloads";

function messageOf(err: unknown, fallback: string): string {
  return err instanceof Error ? err.message : fallback;
}

/** Pre-fill the wizard from the engine's real setup.status (best-effort). */
export async function initFromSetupStatus(
  store: OnboardingFlowStore,
  getStatus: () => Promise<SetupStatus> = getSetupStatus,
): Promise<void> {
  try {
    const status = await getStatus();
    if (status.vault.configured && status.vault.path !== null) {
      setVaultConfigured(store, status.vault.path);
    }
    if (status.models.length > 0 && status.models.every((m) => m.present)) {
      markModelsAlreadyPresent(store);
    }
    if (status.googleConnected) {
      setGoogleResult(store, true, "Connected.");
    }
  } catch {
    // Fresh install / engine still starting: the wizard proceeds from blank.
  }
}

/** Open the Tauri folder picker; a chosen path becomes the pending vault. */
export async function chooseVaultFolder(
  store: OnboardingFlowStore,
  pick: () => Promise<string | null> = pickVaultDirectory,
): Promise<void> {
  try {
    const path = await pick();
    if (path !== null && path.length > 0) setVaultPicked(store, path);
  } catch (err) {
    setVaultError(store, messageOf(err, "Could not open the folder picker."));
  }
}

/**
 * Persist the chosen vault path. `createNew` asks the engine to create the
 * folder; the engine validates writability and may reject — that message is
 * shown verbatim (fail closed, never assumed OK).
 */
export async function configureVault(
  store: OnboardingFlowStore,
  path: string,
  createNew: boolean,
  update = updateSettings,
): Promise<boolean> {
  const trimmed = path.trim();
  if (trimmed.length === 0) {
    setVaultError(store, "Choose a folder or type a path first.");
    return false;
  }
  setVaultBusy(store, true);
  try {
    await update({ vault_dir: trimmed }, createNew);
    setVaultConfigured(store, trimmed);
    return true;
  } catch (err) {
    setVaultError(store, messageOf(err, "The engine could not use that folder."));
    return false;
  }
}

/** Wire the real model-download events into the store. Returns unsubscribe. */
export function subscribeModelDownload(
  store: OnboardingFlowStore,
  socket?: EngineSocketTransport,
): () => void {
  return subscribeToModelsDownload(
    {
      onProgress: (p) =>
        applyModelProgress(store, {
          file: p.file,
          receivedBytes: p.receivedBytes,
          totalBytes: p.totalBytes,
          sha256Verified: p.sha256Verified,
        }),
      onFailed: (f) => applyModelFailed(store, f.file, f.message),
      onCompleted: (c) => markModelsCompleted(store, c.ok),
    },
    socket,
  );
}

/** Kick off the download. Progress/failure/complete arrive via the events. */
export async function beginModelDownload(
  store: OnboardingFlowStore,
  start = startModelsDownload,
): Promise<void> {
  markModelsStarted(store);
  try {
    await start();
  } catch (err) {
    // No events will arrive — mark it failed so the retry button appears.
    applyModelFailed(store, "download", messageOf(err, "Could not start the download."));
    markModelsCompleted(store, false);
  }
}

/** Wire the google.connect.completed event into the store. Returns unsubscribe. */
export function subscribeGoogleConnect(
  store: OnboardingFlowStore,
  socket?: EngineSocketTransport,
): () => void {
  return subscribeToGoogleConnect(
    (c) => setGoogleResult(store, c.ok, c.message),
    socket,
  );
}

/** Begin the Google OAuth connect; the result arrives via the event above. */
export async function beginGoogleConnect(
  store: OnboardingFlowStore,
  connect: typeof connectGoogle = connectGoogle,
  credentials?: { readonly clientId: string; readonly clientSecret: string },
): Promise<void> {
  setGoogleBusy(store, true);
  try {
    await connect(undefined, credentials);
  } catch (err) {
    setGoogleResult(store, false, messageOf(err, "Could not start Google connect."));
  }
}

export function skipGoogleConnect(store: OnboardingFlowStore): void {
  markGoogleSkipped(store);
}

/**
 * Mark onboarding complete, then re-read setup.status to confirm. Calls
 * `onDone` only after the engine confirms — never before.
 */
export async function finishOnboarding(
  store: OnboardingFlowStore,
  onDone: (status: SetupStatus) => void,
  deps: {
    update?: typeof updateSettings;
    getStatus?: () => Promise<SetupStatus>;
  } = {},
): Promise<void> {
  const update = deps.update ?? updateSettings;
  const getStatus = deps.getStatus ?? getSetupStatus;
  setFinishing(store, true);
  try {
    await update({ onboarding_complete: true }, null);
    const status = await getStatus();
    setFinishing(store, false);
    onDone(status);
  } catch (err) {
    setFinishError(store, messageOf(err, "Could not finish setup. Try again."));
  }
}
