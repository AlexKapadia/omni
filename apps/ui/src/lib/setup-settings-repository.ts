/**
 * Typed engine command wrappers for the settings + setup surface. Each wrapper
 * sends a command through the generic ok-reply transport, then validates the
 * reply fail-closed with the payload parsers — a malformed reply throws a
 * plain-voice error, never a silently-coerced object.
 *
 * Security invariants surfaced here: keys.save receives the plaintext key ONCE
 * and this module never retains it; the vault lives in the engine (DPAPI), the
 * UI only relays. Deny by default — an unknown provider never reaches the wire.
 */
import { requestSetupCommand } from "./setup-settings-transport";
import {
  KEYS_SAVE_COMMAND,
  KEYS_VALIDATE_COMMAND,
  LEDGER_SUMMARY_COMMAND,
  MODELS_DOWNLOAD_COMMAND,
  MODELS_CANCEL_COMMAND,
  MODELS_DELETE_COMMAND,
  MODELS_OPEN_FOLDER_COMMAND,
  OLLAMA_MODELS_LIST_COMMAND,
  OLLAMA_MODELS_PULL_COMMAND,
  OLLAMA_PING_COMMAND,
  GOOGLE_CONNECT_COMMAND,
  MICROSOFT_CONNECT_COMMAND,
  SETTINGS_GET_COMMAND,
  SETTINGS_UPDATE_COMMAND,
  SETUP_STATUS_COMMAND,
  type KeyProvider,
} from "./setup-settings-commands";
import {
  parseKeyValidation,
  parseSettingsGet,
  parseSettingsUpdateApplied,
  parseSetupStatus,
  type KeyValidationResult,
  type SettingsGetResult,
  type SetupStatus,
} from "./setup-settings-payloads";
import { parseLedgerSummary, type LedgerSummary } from "./ledger-summary-payload";
import {
  parseOllamaModelsList,
  parseOllamaPingResult,
  type OllamaModel,
  type OllamaPingResult,
} from "./ollama-commands";
import { asNonEmptyString } from "./untrusted-payload-guards";

/** The command seam — real transport by default, a fake in tests. */
export type SetupRequestFn = (
  name: string,
  payload?: Record<string, unknown>,
  timeoutMs?: number,
) => Promise<Record<string, unknown>>;

/** Ledger + status reads are quick; a key validation makes a real call. */
const READ_TIMEOUT_MS = 15_000;
const VALIDATE_TIMEOUT_MS = 30_000;

export async function getSettings(
  request: SetupRequestFn = requestSetupCommand,
): Promise<SettingsGetResult> {
  const payload = await request(SETTINGS_GET_COMMAND, {}, READ_TIMEOUT_MS);
  const result = parseSettingsGet(payload);
  if (result === null) throw new Error("the engine sent malformed settings");
  return result;
}

export async function getSetupStatus(
  request: SetupRequestFn = requestSetupCommand,
): Promise<SetupStatus> {
  const payload = await request(SETUP_STATUS_COMMAND, {}, READ_TIMEOUT_MS);
  const status = parseSetupStatus(payload);
  if (status === null) throw new Error("the engine sent a malformed setup status");
  return status;
}

/**
 * Persist a settings change. `values` is the partial the engine will apply;
 * `createVaultDir` (vault picker only) asks the engine to create the folder.
 * Returns the engine's echo of what it actually applied.
 *
 * Contract note (verified with the engine lane): settings.update rejects extra
 * top-level fields, so `create_vault_dir` rides INSIDE the `values` map — never
 * as a sibling of `values` (that fails with settings_error / INVALID_PAYLOAD).
 * The engine consumes it and never echoes it back in `applied`.
 */
export async function updateSettings(
  values: Record<string, unknown>,
  createVaultDir: boolean | null = null,
  request: SetupRequestFn = requestSetupCommand,
): Promise<Record<string, unknown>> {
  const mergedValues =
    createVaultDir !== null ? { ...values, create_vault_dir: createVaultDir } : values;
  const payload = await request(SETTINGS_UPDATE_COMMAND, { values: mergedValues }, READ_TIMEOUT_MS);
  const applied = parseSettingsUpdateApplied(payload);
  if (applied === null) throw new Error("the engine did not confirm the change");
  return applied;
}

/**
 * Hand one key's plaintext to the engine vault ONCE. The value flows straight
 * through; nothing here retains it (the DPAPI vault lives in the engine).
 */
export async function saveKey(
  provider: KeyProvider,
  key: string,
  request: SetupRequestFn = requestSetupCommand,
): Promise<void> {
  await request(KEYS_SAVE_COMMAND, { provider, key }, READ_TIMEOUT_MS);
}

export async function validateKey(
  provider: KeyProvider,
  request: SetupRequestFn = requestSetupCommand,
): Promise<KeyValidationResult> {
  const payload = await request(KEYS_VALIDATE_COMMAND, { provider }, VALIDATE_TIMEOUT_MS);
  const result = parseKeyValidation(payload);
  if (result === null) throw new Error("the engine sent a malformed validation result");
  return { provider, ...result };
}

export async function getLedgerSummary(
  limit = 20,
  request: SetupRequestFn = requestSetupCommand,
): Promise<LedgerSummary> {
  const payload = await request(LEDGER_SUMMARY_COMMAND, { limit }, READ_TIMEOUT_MS);
  const summary = parseLedgerSummary(payload);
  if (summary === null) throw new Error("the engine sent a malformed ledger");
  return summary;
}

/** Kick off the model download; progress arrives as events (subscribe first). */
export async function startModelsDownload(
  request: SetupRequestFn = requestSetupCommand,
  options?: { readonly bundle?: "core" | "whisper"; readonly modelId?: string },
): Promise<void> {
  const payload =
    options?.bundle === "whisper" && options.modelId
      ? { bundle: "whisper", model_id: options.modelId }
      : options?.bundle === "core"
        ? { bundle: "core" }
        : {};
  await request(MODELS_DOWNLOAD_COMMAND, payload, READ_TIMEOUT_MS);
}

/**
 * List locally-installed Ollama models; the pull progress arrives as events.
 *
 * Contract note: the `ollama.*` commands take NO base-url argument — the
 * engine resolves its own host from `OMNI_OLLAMA_BASE_URL`, which the
 * `ollama_base_url` settings.update call keeps in lockstep (see
 * `app_settings_command_gateway`). Sending a `base_url` field here would be
 * refused outright (the payload schema is `extra="forbid"`).
 */
export async function listOllamaModels(
  request: SetupRequestFn = requestSetupCommand,
): Promise<readonly OllamaModel[]> {
  const reply = await request(OLLAMA_MODELS_LIST_COMMAND, {}, READ_TIMEOUT_MS);
  const models = parseOllamaModelsList(reply);
  if (models === null) throw new Error("the engine sent a malformed model list");
  return models;
}

/** Kick off an Ollama model pull; progress arrives as ollama.pull.* events. */
export async function pullOllamaModel(
  model: string,
  request: SetupRequestFn = requestSetupCommand,
): Promise<void> {
  await request(OLLAMA_MODELS_PULL_COMMAND, { model }, READ_TIMEOUT_MS);
}

/** Test connectivity to the Ollama endpoint; a real (bounded) round trip. */
export async function pingOllama(
  request: SetupRequestFn = requestSetupCommand,
): Promise<OllamaPingResult> {
  const reply = await request(OLLAMA_PING_COMMAND, {}, VALIDATE_TIMEOUT_MS);
  const result = parseOllamaPingResult(reply);
  if (result === null) throw new Error("the engine sent a malformed ping result");
  return result;
}

/** Cancel whatever models download (Whisper/core/Ollama pull) is in flight. */
export async function cancelModelsDownload(
  request: SetupRequestFn = requestSetupCommand,
): Promise<void> {
  await request(MODELS_CANCEL_COMMAND, {}, READ_TIMEOUT_MS);
}

/** Delete one installed model file (e.g. a Whisper ggml). */
export async function deleteModelFile(
  file: string,
  request: SetupRequestFn = requestSetupCommand,
): Promise<void> {
  await request(MODELS_DELETE_COMMAND, { file }, READ_TIMEOUT_MS);
}

/** Ask the engine for the real on-device models folder path. */
export async function openModelsFolder(
  request: SetupRequestFn = requestSetupCommand,
): Promise<string> {
  const reply = await request(MODELS_OPEN_FOLDER_COMMAND, {}, READ_TIMEOUT_MS);
  const path = asNonEmptyString(reply["path"]);
  if (path === null) throw new Error("the engine did not return the models folder path");
  return path;
}

/** Begin the Google OAuth connect; completion arrives as an event. */
export async function connectGoogle(
  request: SetupRequestFn = requestSetupCommand,
  credentials?: { readonly clientId: string; readonly clientSecret: string },
): Promise<void> {
  const payload =
    credentials !== undefined
      ? { client_id: credentials.clientId.trim(), client_secret: credentials.clientSecret.trim() }
      : {};
  await request(GOOGLE_CONNECT_COMMAND, payload, READ_TIMEOUT_MS);
}

/** Begin the Microsoft OAuth connect; completion arrives as an event. */
export async function connectMicrosoft(
  request: SetupRequestFn = requestSetupCommand,
  credentials?: { readonly clientId: string; readonly clientSecret: string },
): Promise<void> {
  const payload =
    credentials !== undefined
      ? { client_id: credentials.clientId.trim(), client_secret: credentials.clientSecret.trim() }
      : {};
  await request(MICROSOFT_CONNECT_COMMAND, payload, READ_TIMEOUT_MS);
}
