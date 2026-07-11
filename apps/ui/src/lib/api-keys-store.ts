/**
 * Zustand store for API key entry + validation state — deliberately value-free.
 *
 * Security invariant (binding): a key's plaintext NEVER lives in UI state and
 * is NEVER echoed back into the DOM after save. The value flows once, from the
 * masked input straight into the ApiKeyVault interface (engine DPAPI in
 * production), and only `{ saved, lastFour }` metadata plus validation status
 * remains renderable. The UI process never holds keys at rest.
 */
import { createStore, useStore, type StoreApi } from "zustand";
import { KEY_PROVIDERS, type KeyProvider } from "./setup-settings-commands";
import { saveKey, validateKey } from "./setup-settings-repository";
import type { KeyValidationResult } from "./setup-settings-payloads";

export { KEY_PROVIDERS, KEY_PROVIDER_LABELS, type KeyProvider } from "./setup-settings-commands";

/** Where key plaintext goes — and the only place it goes. DPAPI in the engine. */
export interface ApiKeyVault {
  persistKey(provider: KeyProvider, value: string): Promise<void>;
}

export interface ApiKeyRowState {
  readonly saved: boolean;
  /** Last four characters only — enough to recognise a key, never recover it. */
  readonly lastFour: string | null;
}

export type KeyValidationStatus = "idle" | "validating" | "valid" | "invalid" | "error";

export interface KeyValidationState {
  readonly status: KeyValidationStatus;
  /** The engine's own message — verbatim, never invented. */
  readonly message: string | null;
  readonly latencyMs: number | null;
}

export interface ApiKeysState {
  readonly keys: Readonly<Record<KeyProvider, ApiKeyRowState>>;
  readonly validation: Readonly<Record<KeyProvider, KeyValidationState>>;
  readonly savingProvider: KeyProvider | null;
  readonly errorMessage: string | null;
}

const IDLE_VALIDATION: KeyValidationState = { status: "idle", message: null, latencyMs: null };

function blankRows<T>(value: T): Readonly<Record<KeyProvider, T>> {
  const out = {} as Record<KeyProvider, T>;
  for (const provider of KEY_PROVIDERS) out[provider] = value;
  return out;
}

export const INITIAL_API_KEYS_STATE: ApiKeysState = {
  keys: blankRows<ApiKeyRowState>({ saved: false, lastFour: null }),
  validation: blankRows<KeyValidationState>(IDLE_VALIDATION),
  savingProvider: null,
  errorMessage: null,
};

export type ApiKeysStore = StoreApi<ApiKeysState>;

export function createApiKeysStore(): ApiKeysStore {
  return createStore<ApiKeysState>(() => INITIAL_API_KEYS_STATE);
}

/** The one store the running app uses. Tests create their own via the factory. */
export const apiKeysStore: ApiKeysStore = createApiKeysStore();

export function useApiKeys<T>(selector: (state: ApiKeysState) => T): T {
  return useStore(apiKeysStore, selector);
}

const MIN_KEY_LENGTH = 8;

/**
 * Persist one key. Validation is fail-closed; on success only metadata is
 * stored. The `value` argument is deliberately not retained anywhere. Saving a
 * new key resets that provider's validation status (the old verdict is stale).
 */
export async function saveApiKey(
  store: ApiKeysStore,
  vault: ApiKeyVault,
  provider: KeyProvider,
  value: string,
): Promise<boolean> {
  const trimmed = value.trim();
  if (trimmed.length < MIN_KEY_LENGTH) {
    store.setState({ errorMessage: "That key looks too short. Paste the full key." });
    return false;
  }
  if (/\s/.test(trimmed)) {
    store.setState({ errorMessage: "Keys cannot contain spaces. Check the paste." });
    return false;
  }
  store.setState({ savingProvider: provider, errorMessage: null });
  try {
    await vault.persistKey(provider, trimmed);
    store.setState((state) => ({
      savingProvider: null,
      keys: { ...state.keys, [provider]: { saved: true, lastFour: trimmed.slice(-4) } },
      validation: { ...state.validation, [provider]: IDLE_VALIDATION },
    }));
    return true;
  } catch {
    // Fail closed: an unsaved key is reported, never silently assumed saved.
    store.setState({ savingProvider: null, errorMessage: "Could not save the key. Try again." });
    return false;
  }
}

/** The validate seam — real keys.validate by default, a fake in tests. */
export type KeyValidator = (provider: KeyProvider) => Promise<KeyValidationResult>;

/**
 * Validate one saved key against its provider with a REAL 1-token call. The
 * verdict, message and latency are the engine's own — "✓ Valid" only ever
 * follows a genuine success (fail closed: any error shows honestly).
 */
export async function validateApiKey(
  store: ApiKeysStore,
  validate: KeyValidator,
  provider: KeyProvider,
): Promise<boolean> {
  store.setState((state) => ({
    validation: {
      ...state.validation,
      [provider]: { status: "validating", message: null, latencyMs: null },
    },
  }));
  try {
    const result = await validate(provider);
    store.setState((state) => ({
      validation: {
        ...state.validation,
        [provider]: {
          status: result.valid ? "valid" : "invalid",
          message: result.message,
          latencyMs: result.latencyMs,
        },
      },
    }));
    return result.valid;
  } catch (err) {
    store.setState((state) => ({
      validation: {
        ...state.validation,
        [provider]: {
          status: "error",
          message: err instanceof Error ? err.message : "Validation failed.",
          latencyMs: null,
        },
      },
    }));
    return false;
  }
}

/**
 * The REAL key vault: hands plaintext to the engine's keys.save (DPAPI) ONCE
 * and never reads back — there is deliberately no read path.
 */
export function createEngineApiKeyVault(persist = saveKey): ApiKeyVault {
  return { persistKey: (provider, value) => persist(provider, value) };
}

/** The REAL validator, bound to the engine's keys.validate command. */
export const engineKeyValidator: KeyValidator = (provider) => validateKey(provider);

/**
 * Apply setup.status key PRESENCE flags into the store after restart.
 * setup.status returns booleans only (never key material / last fours), so
 * saved keys get a masked placeholder lastFour — enough for UI chrome
 * (Naomi visibility, Settings "saved" badges) without inventing digits.
 */
export function hydrateApiKeysFromSetupStatus(
  store: ApiKeysStore,
  flags: Readonly<Record<KeyProvider, boolean>>,
): void {
  const keys = {} as Record<KeyProvider, ApiKeyRowState>;
  for (const provider of KEY_PROVIDERS) {
    const present = flags[provider] === true;
    keys[provider] = present
      ? { saved: true, lastFour: "••••" }
      : { saved: false, lastFour: null };
  }
  store.setState({ keys });
}

/**
 * MOCK ApiKeyVault — in-memory sink for tests only. Same interface, and it
 * deliberately does NOT expose a read path, so nothing can echo a stored value.
 */
export function createMockApiKeyVault(): ApiKeyVault {
  return { persistKey: () => Promise.resolve() };
}
