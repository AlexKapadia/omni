/**
 * Zustand store for API key entry state — deliberately value-free.
 *
 * Security invariant (binding): a key's plaintext NEVER lives in UI state and
 * is NEVER echoed back into the DOM after save. The value flows once, from
 * the masked input straight into the ApiKeyVault interface, and only
 * `{ saved, lastFour }` metadata remains renderable. The mock vault below is
 * in-memory; the real vault is DPAPI in the engine process (the UI process
 * never holds keys at rest).
 */
import { createStore, useStore, type StoreApi } from "zustand";

export type KeyProvider = "groq" | "gemini" | "anthropic";

export const KEY_PROVIDERS: readonly KeyProvider[] = ["groq", "gemini", "anthropic"];

export const KEY_PROVIDER_LABELS: Readonly<Record<KeyProvider, string>> = {
  groq: "Groq",
  gemini: "Gemini",
  anthropic: "Claude",
};

/** Where key plaintext goes — and the only place it goes. DPAPI later. */
export interface ApiKeyVault {
  persistKey(provider: KeyProvider, value: string): Promise<void>;
}

export interface ApiKeyRowState {
  readonly saved: boolean;
  /** Last four characters only — enough to recognise a key, never recover it. */
  readonly lastFour: string | null;
}

export interface ApiKeysState {
  readonly keys: Readonly<Record<KeyProvider, ApiKeyRowState>>;
  readonly savingProvider: KeyProvider | null;
  readonly errorMessage: string | null;
}

export const INITIAL_API_KEYS_STATE: ApiKeysState = {
  keys: {
    groq: { saved: false, lastFour: null },
    gemini: { saved: false, lastFour: null },
    anthropic: { saved: false, lastFour: null },
  },
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
 * stored. The `value` argument is deliberately not retained anywhere.
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
      keys: {
        ...state.keys,
        [provider]: { saved: true, lastFour: trimmed.slice(-4) },
      },
    }));
    return true;
  } catch {
    // Fail closed: an unsaved key is reported, never silently assumed saved.
    store.setState({ savingProvider: null, errorMessage: "Could not save the key. Try again." });
    return false;
  }
}

/**
 * MOCK ApiKeyVault — in-memory sink until the engine's DPAPI vault endpoint
 * lands. Clearly-marked mock: same interface, and it deliberately does NOT
 * expose a read path, so nothing can ever echo a stored value back out.
 */
export function createMockApiKeyVault(): ApiKeyVault {
  return {
    persistKey: () => new Promise((resolve) => setTimeout(resolve, 250)),
  };
}
