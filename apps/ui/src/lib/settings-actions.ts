/**
 * Async orchestration for the Settings store: load the real settings + ledger,
 * and apply a control change optimistically with an honest revert if the
 * engine refuses. Kept apart from settings-store.ts so the pure state is
 * testable without a socket, and so a control never lies about what persisted.
 *
 * Security binding: a kill-switch change re-reads settings.get so the UI shows
 * the engine's true engaged state, never an assumed one.
 */
import {
  applyLedger,
  applySettingsResult,
  markLedgerError,
  markSettingsError,
  patchSettings,
  type SettingsStore,
} from "./settings-store";
import type { EngineSettings } from "./setup-settings-payloads";
import { getLedgerSummary, getSettings, updateSettings } from "./setup-settings-repository";
import { requestSetupCommand, type EngineSocketTransport } from "./setup-settings-transport";
import type { SetupRequestFn } from "./setup-settings-repository";

/** The default request seam bound to the live socket (overridable in tests). */
export function liveRequest(socket?: EngineSocketTransport): SetupRequestFn {
  return (name, payload = {}, timeoutMs) => requestSetupCommand(name, payload, timeoutMs, socket);
}

function messageOf(err: unknown): string {
  return err instanceof Error ? err.message : "the engine refused the change";
}

/** Fetch settings.get and fill the store, or mark the load honestly failed. */
export async function loadSettings(
  store: SettingsStore,
  request: SetupRequestFn = requestSetupCommand,
): Promise<void> {
  try {
    applySettingsResult(store, await getSettings(request));
  } catch (err) {
    markSettingsError(store, messageOf(err));
  }
}

/** Fetch ledger.summary and fill the store, or mark it honestly failed. */
export async function loadLedger(
  store: SettingsStore,
  limit = 20,
  request: SetupRequestFn = requestSetupCommand,
): Promise<void> {
  try {
    applyLedger(store, await getLedgerSummary(limit, request));
  } catch (err) {
    markLedgerError(store, messageOf(err));
  }
}

/** Map a camelCase settings partial to the snake_case wire values. */
function toWireValues(partial: Partial<EngineSettings>): Record<string, unknown> {
  const values: Record<string, unknown> = {};
  if (partial.vaultDir !== undefined) values["vault_dir"] = partial.vaultDir;
  if (partial.pushToTalkHotkey !== undefined) values["push_to_talk_hotkey"] = partial.pushToTalkHotkey;
  if (partial.keepAudio !== undefined) values["keep_audio"] = partial.keepAudio;
  if (partial.disclosureReminder !== undefined) {
    values["disclosure_reminder"] = partial.disclosureReminder;
  }
  if (partial.killSwitch !== undefined) values["kill_switch"] = partial.killSwitch;
  if (partial.instantExecuteWhitelist !== undefined) {
    values["instant_execute_whitelist"] = partial.instantExecuteWhitelist;
  }
  if (partial.activeTemplate !== undefined) values["active_template"] = partial.activeTemplate;
  if (partial.customTemplates !== undefined) values["custom_templates"] = partial.customTemplates;
  if (partial.onboardingComplete !== undefined) {
    values["onboarding_complete"] = partial.onboardingComplete;
  }
  return values;
}

export interface UpdateResult {
  readonly ok: boolean;
  readonly message: string | null;
}

/** A store-and-transport-bound updater the section components consume. */
export type SettingsUpdater = (partial: Partial<EngineSettings>) => Promise<UpdateResult>;

/**
 * Apply a settings change optimistically, then persist it. On refusal, revert
 * the optimistic patch and surface the engine's own message — a control never
 * shows a state the engine did not accept.
 */
export async function updateSetting(
  store: SettingsStore,
  partial: Partial<EngineSettings>,
  request: SetupRequestFn = requestSetupCommand,
): Promise<UpdateResult> {
  const previous = store.getState().settings;
  patchSettings(store, partial); // optimistic — snappy, but revertible
  try {
    await updateSettings(toWireValues(partial), null, request);
    // A kill-switch change alters the live engaged state — re-read the truth.
    if (partial.killSwitch !== undefined) {
      applySettingsResult(store, await getSettings(request));
    }
    return { ok: true, message: null };
  } catch (err) {
    if (previous !== null) store.setState({ settings: previous }); // honest revert
    return { ok: false, message: messageOf(err) };
  }
}
