/**
 * Pinned command and event NAMES for the M7 setup + settings surface, plus the
 * closed provider and intent-type vocabularies. One place so every caller uses
 * the exact wire string the engine lands behind the same contract — a typo
 * here would silently break a control, so the strings live once.
 *
 * Security invariant: the provider and intent sets are CLOSED (deny by
 * default). Anything outside them is refused before it can reach the engine.
 */

/** Request/reply commands (all reply `ok` on success, `error` on refusal). */
export const SETTINGS_GET_COMMAND = "settings.get";
export const SETTINGS_UPDATE_COMMAND = "settings.update";
export const SETUP_STATUS_COMMAND = "setup.status";
export const KEYS_SAVE_COMMAND = "keys.save";
export const KEYS_VALIDATE_COMMAND = "keys.validate";
export const LEDGER_SUMMARY_COMMAND = "ledger.summary";
export const MODELS_DOWNLOAD_COMMAND = "models.download";
export const GOOGLE_CONNECT_COMMAND = "google.connect";
export const MICROSOFT_CONNECT_COMMAND = "microsoft.connect";

/** Streaming events (correlated by name, not by reply id). */
export const MODELS_DOWNLOAD_PROGRESS_EVENT = "models.download.progress";
export const MODELS_DOWNLOAD_FAILED_EVENT = "models.download.failed";
export const MODELS_DOWNLOAD_COMPLETED_EVENT = "models.download.completed";
export const GOOGLE_CONNECT_COMPLETED_EVENT = "google.connect.completed";
export const MICROSOFT_CONNECT_COMPLETED_EVENT = "microsoft.connect.completed";
export const CALENDAR_UPCOMING_EVENT = "calendar.upcoming";

/**
 * API-key providers. Groq + Gemini are required for a working install; Claude
 * (anthropic) and Cartesia are optional per-task providers.
 */
export type KeyProvider =
  | "groq"
  | "gemini"
  | "anthropic"
  | "openai"
  | "openrouter"
  | "azure_openai"
  | "cartesia";

export const KEY_PROVIDERS: readonly KeyProvider[] = [
  "groq",
  "gemini",
  "anthropic",
  "openai",
  "openrouter",
  "azure_openai",
  "cartesia",
];

/** Providers a working install cannot skip (deny finish until both validate). */
export const REQUIRED_KEY_PROVIDERS: readonly KeyProvider[] = ["groq", "gemini"];

/** Human-facing provider names (the engine copy is stale — data from here). */
export const KEY_PROVIDER_LABELS: Readonly<Record<KeyProvider, string>> = {
  groq: "Groq",
  gemini: "Gemini",
  anthropic: "Claude",
  openai: "OpenAI",
  openrouter: "OpenRouter",
  azure_openai: "Azure OpenAI",
  cartesia: "Cartesia",
};

/**
 * The four action intents an approval card can carry. The instant-execute
 * whitelist lets a matching dictation intent run WITHOUT a card — so this set
 * is closed and every member defaults OFF (deny by default; §5.6).
 */
export type InstantIntentType = "create_event" | "upsert_contact" | "draft_email" | "write_note";

export const INSTANT_INTENT_TYPES: readonly InstantIntentType[] = [
  "create_event",
  "upsert_contact",
  "draft_email",
  "write_note",
];

/** Type guard used when parsing an untrusted whitelist array (fail closed). */
export function isInstantIntentType(value: unknown): value is InstantIntentType {
  return (
    value === "create_event" ||
    value === "upsert_contact" ||
    value === "draft_email" ||
    value === "write_note"
  );
}
