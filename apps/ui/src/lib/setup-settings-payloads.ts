/**
 * Fail-closed parsers + domain types for the settings.get / setup.status /
 * keys.validate / settings.update replies. Every field of every reply is
 * untrusted input: a malformed field rejects the whole payload (returns null)
 * rather than being coerced into the UI.
 *
 * The design doc's provider/model copy is stale by contract — the shapes here
 * mirror the REAL engine reply, and the layouts consume them.
 */
import {
  isInstantIntentType,
  type InstantIntentType,
  type KeyProvider,
} from "./setup-settings-commands";
import {
  asBoolean,
  asFiniteNumber,
  asFiniteNumberOrNull,
  asNonEmptyString,
  asString,
  isPlainObject,
} from "./untrusted-payload-guards";

// ------------------------------------------------------------ settings.get
export interface EngineSettings {
  /** Absolute vault path, or null until the user picks one in onboarding. */
  readonly vaultDir: string | null;
  readonly pushToTalkHotkey: readonly string[];
  readonly keepAudio: boolean; // default false — discard after transcription
  readonly disclosureReminder: boolean;
  readonly killSwitch: boolean; // the user's setting (engaged state is separate)
  readonly instantExecuteWhitelist: readonly InstantIntentType[];
  readonly activeTemplate: string;
  readonly customTemplates: readonly string[];
  readonly onboardingComplete: boolean;
}

export interface RoutingAttempt {
  readonly provider: string;
  readonly model: string;
}

export interface RoutingRow {
  readonly task: string;
  readonly onDevice: boolean;
  readonly attempts: readonly RoutingAttempt[];
  // null for on-device tasks (transcription/embeddings) — no latency budget
  // applies; the engine sends budget_ms: null for these. Cloud tasks carry a
  // finite millisecond budget.
  readonly budgetMs: number | null;
}

export interface TemplateOption {
  readonly templateId: string;
  readonly displayName: string;
  readonly builtin: boolean;
}

export interface SettingsGetResult {
  readonly settings: EngineSettings;
  readonly killSwitchEngaged: boolean;
  readonly routing: readonly RoutingRow[];
  readonly templateOptions: readonly TemplateOption[];
}

/** Accept either a string[] hotkey or a "Ctrl+Shift+Space" string. */
function parseHotkey(value: unknown): readonly string[] | null {
  if (Array.isArray(value)) {
    const keys = value.filter((k): k is string => typeof k === "string" && k.length > 0);
    return keys.length === value.length && keys.length > 0 ? keys : null;
  }
  if (typeof value === "string" && value.length > 0) {
    const keys = value.split(/[+\s]+/).filter((k) => k.length > 0);
    return keys.length > 0 ? keys : null;
  }
  return null;
}

/** Keep recognised intents; drop unknown (deny by default); reject non-array. */
function parseWhitelist(value: unknown): readonly InstantIntentType[] | null {
  if (!Array.isArray(value)) return null;
  const seen = new Set<InstantIntentType>();
  for (const item of value) {
    if (isInstantIntentType(item)) seen.add(item);
    // Unknown-but-string members are ignored (forward compatible, deny by
    // default); this never enables an intent the UI cannot represent.
  }
  return [...seen];
}

function parseStringArray(value: unknown): readonly string[] | null {
  if (!Array.isArray(value)) return null;
  const out: string[] = [];
  for (const item of value) {
    if (typeof item !== "string") return null; // corruption — fail closed
    out.push(item);
  }
  return out;
}

function parseEngineSettings(value: unknown): EngineSettings | null {
  if (!isPlainObject(value)) return null;
  const vaultDir = value["vault_dir"] === null ? null : asNonEmptyString(value["vault_dir"]);
  if (vaultDir === null && value["vault_dir"] !== null) return null;
  const hotkey = parseHotkey(value["push_to_talk_hotkey"]);
  const keepAudio = asBoolean(value["keep_audio"]);
  const disclosureReminder = asBoolean(value["disclosure_reminder"]);
  const killSwitch = asBoolean(value["kill_switch"]);
  const whitelist = parseWhitelist(value["instant_execute_whitelist"]);
  const activeTemplate = asString(value["active_template"]);
  const customTemplates = parseStringArray(value["custom_templates"]);
  const onboardingComplete = asBoolean(value["onboarding_complete"]);
  if (hotkey === null || keepAudio === null || disclosureReminder === null) return null;
  if (killSwitch === null || whitelist === null || activeTemplate === null) return null;
  if (customTemplates === null || onboardingComplete === null) return null;
  return {
    vaultDir,
    pushToTalkHotkey: hotkey,
    keepAudio,
    disclosureReminder,
    killSwitch,
    instantExecuteWhitelist: whitelist,
    activeTemplate,
    customTemplates,
    onboardingComplete,
  };
}

function parseRoutingRow(value: unknown): RoutingRow | null {
  if (!isPlainObject(value)) return null;
  const task = asNonEmptyString(value["task"]);
  const onDevice = asBoolean(value["on_device"]);
  // budget_ms is nullable in the engine contract (on-device tasks have no
  // budget). Accept null; reject only a present-but-non-numeric value.
  const rawBudget = value["budget_ms"];
  const budgetMs = rawBudget === null ? null : asFiniteNumber(rawBudget);
  const attemptsRaw = value["attempts"];
  if (task === null || onDevice === null || !Array.isArray(attemptsRaw)) {
    return null;
  }
  if (rawBudget !== null && budgetMs === null) return null; // corrupt budget
  const attempts: RoutingAttempt[] = [];
  for (const raw of attemptsRaw) {
    if (!isPlainObject(raw)) return null;
    const provider = asNonEmptyString(raw["provider"]);
    const model = asString(raw["model"]);
    if (provider === null || model === null) return null;
    attempts.push({ provider, model });
  }
  return { task, onDevice, attempts, budgetMs };
}

function parseTemplateOption(value: unknown): TemplateOption | null {
  if (!isPlainObject(value)) return null;
  const templateId = asNonEmptyString(value["template_id"]);
  const displayName = asNonEmptyString(value["display_name"]);
  const builtin = asBoolean(value["builtin"]);
  if (templateId === null || displayName === null || builtin === null) return null;
  return { templateId, displayName, builtin };
}

function parseList<T>(value: unknown, parseItem: (raw: unknown) => T | null): readonly T[] | null {
  if (!Array.isArray(value)) return null;
  const out: T[] = [];
  for (const raw of value) {
    const item = parseItem(raw);
    if (item === null) return null; // one bad row rejects the whole list
    out.push(item);
  }
  return out;
}

/** Validate a settings.get reply payload fail-closed; null on any deviation. */
export function parseSettingsGet(payload: Record<string, unknown>): SettingsGetResult | null {
  if (!isPlainObject(payload)) return null; // defense in depth
  const settings = parseEngineSettings(payload["settings"]);
  const killSwitchEngaged = asBoolean(payload["kill_switch_engaged"]);
  const routing = parseList(payload["routing"], parseRoutingRow);
  const templateOptions = parseList(payload["template_options"], parseTemplateOption);
  if (settings === null || killSwitchEngaged === null) return null;
  if (routing === null || templateOptions === null) return null;
  return { settings, killSwitchEngaged, routing, templateOptions };
}

/** settings.update reply: the engine's echo of what it actually applied. */
export function parseSettingsUpdateApplied(
  payload: Record<string, unknown>,
): Record<string, unknown> | null {
  const applied = payload["applied"];
  return isPlainObject(applied) ? applied : null;
}

// ------------------------------------------------------------- setup.status
export interface SetupModelStatus {
  readonly file: string;
  readonly present: boolean;
  readonly bytes: number;
}

export interface SetupStatus {
  readonly keys: Readonly<Record<KeyProvider, boolean>>;
  readonly vault: { readonly configured: boolean; readonly path: string | null };
  readonly models: readonly SetupModelStatus[];
  readonly googleConnected: boolean;
  readonly onboardingComplete: boolean;
  readonly setupComplete: boolean;
}

function parseKeyFlags(value: unknown): Readonly<Record<KeyProvider, boolean>> | null {
  if (!isPlainObject(value)) return null;
  const groq = asBoolean(value["groq"]);
  const gemini = asBoolean(value["gemini"]);
  const anthropic = asBoolean(value["anthropic"]);
  const cartesia = asBoolean(value["cartesia"]);
  if (groq === null || gemini === null || anthropic === null || cartesia === null) return null;
  return { groq, gemini, anthropic, cartesia };
}

function parseModel(value: unknown): SetupModelStatus | null {
  if (!isPlainObject(value)) return null;
  const file = asNonEmptyString(value["file"]);
  const present = asBoolean(value["present"]);
  const bytes = asFiniteNumber(value["bytes"]);
  if (file === null || present === null || bytes === null) return null;
  return { file, present, bytes };
}

/** Validate a setup.status reply payload fail-closed; null on any deviation. */
export function parseSetupStatus(payload: Record<string, unknown>): SetupStatus | null {
  if (!isPlainObject(payload)) return null; // defense in depth
  const keys = parseKeyFlags(payload["keys"]);
  const vaultRaw = payload["vault"];
  const models = parseList(payload["models"], parseModel);
  const googleConnected = asBoolean(payload["google_connected"]);
  const onboardingComplete = asBoolean(payload["onboarding_complete"]);
  const setupComplete = asBoolean(payload["setup_complete"]);
  if (keys === null || !isPlainObject(vaultRaw) || models === null) return null;
  if (googleConnected === null || onboardingComplete === null || setupComplete === null) return null;
  const configured = asBoolean(vaultRaw["configured"]);
  const path = vaultRaw["path"] === null ? null : asNonEmptyString(vaultRaw["path"]);
  if (configured === null || (path === null && vaultRaw["path"] !== null)) return null;
  return {
    keys,
    vault: { configured, path },
    models,
    googleConnected,
    onboardingComplete,
    setupComplete,
  };
}

// ------------------------------------------------------------ keys.validate
export interface KeyValidationResult {
  readonly provider: KeyProvider;
  readonly valid: boolean;
  readonly message: string;
  readonly latencyMs: number | null;
}

/** Validate a keys.validate reply payload fail-closed; null on any deviation. */
export function parseKeyValidation(
  payload: Record<string, unknown>,
): Omit<KeyValidationResult, "provider"> | null {
  if (!isPlainObject(payload)) return null; // defense in depth
  const valid = asBoolean(payload["valid"]);
  const message = asString(payload["message"]);
  const latency = asFiniteNumberOrNull(payload["latency_ms"]);
  if (valid === null || message === null || latency === undefined) return null;
  return { valid, message, latencyMs: latency };
}
