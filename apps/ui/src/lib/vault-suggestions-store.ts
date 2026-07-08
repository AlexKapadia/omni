/**
 * Proactive vault suggestions from `vault.suggestion` events.
 */
import { createStore, useStore, type StoreApi } from "zustand";

export const VAULT_SUGGESTION_EVENT_NAME = "vault.suggestion";

export interface VaultSuggestionSource {
  readonly notePath: string;
  readonly lineStart: number;
  readonly lineEnd: number;
  readonly headingPath: string;
  readonly snippet: string;
  readonly score: number;
}

export interface VaultSuggestion {
  readonly id: string;
  readonly topic: string;
  readonly latencyMs: number;
  readonly sources: readonly VaultSuggestionSource[];
}

export interface VaultSuggestionsState {
  readonly suggestions: readonly VaultSuggestion[];
}

export const MAX_VAULT_SUGGESTIONS = 10;

export const INITIAL_VAULT_SUGGESTIONS_STATE: VaultSuggestionsState = { suggestions: [] };

export type VaultSuggestionsStore = StoreApi<VaultSuggestionsState>;

export function createVaultSuggestionsStore(): VaultSuggestionsStore {
  return createStore<VaultSuggestionsState>(() => INITIAL_VAULT_SUGGESTIONS_STATE);
}

export const vaultSuggestionsStore: VaultSuggestionsStore = createVaultSuggestionsStore();

export function useVaultSuggestions<T>(selector: (state: VaultSuggestionsState) => T): T {
  return useStore(vaultSuggestionsStore, selector);
}

function isPlainObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function parseSource(value: unknown): VaultSuggestionSource | null {
  if (!isPlainObject(value)) return null;
  const notePath = value["note_path"];
  const lineStart = value["line_start"];
  const lineEnd = value["line_end"];
  const headingPath = value["heading_path"];
  const snippet = value["snippet"];
  const score = value["score"];
  if (typeof notePath !== "string" || notePath.length === 0) return null;
  if (typeof lineStart !== "number" || !Number.isInteger(lineStart) || lineStart < 1) return null;
  if (typeof lineEnd !== "number" || !Number.isInteger(lineEnd) || lineEnd < lineStart) return null;
  if (typeof headingPath !== "string" || typeof snippet !== "string") return null;
  if (typeof score !== "number" || !Number.isFinite(score)) return null;
  return { notePath, lineStart, lineEnd, headingPath, snippet, score };
}

export function parseVaultSuggestionPayload(payload: unknown): VaultSuggestion | null {
  if (!isPlainObject(payload)) return null;
  const topic = payload["topic"];
  const latencyMs = payload["latency_ms"];
  const hits = payload["hits"];
  if (typeof topic !== "string" || topic.length === 0) return null;
  if (typeof latencyMs !== "number" || !Number.isFinite(latencyMs)) return null;
  if (!Array.isArray(hits) || hits.length === 0) return null;
  const sources: VaultSuggestionSource[] = [];
  for (const raw of hits) {
    const source = parseSource(raw);
    if (source === null) return null;
    sources.push(source);
  }
  const id = topic.toLowerCase().replace(/\W+/g, "-").slice(0, 64);
  return { id, topic, latencyMs, sources };
}

export function applyVaultSuggestion(store: VaultSuggestionsStore, payload: unknown): void {
  const parsed = parseVaultSuggestionPayload(payload);
  if (parsed === null) return;
  store.setState((state) => {
    const without = state.suggestions.filter((s) => s.id !== parsed.id);
    return { suggestions: [parsed, ...without].slice(0, MAX_VAULT_SUGGESTIONS) };
  });
}

export function clearVaultSuggestions(store: VaultSuggestionsStore): void {
  store.setState(INITIAL_VAULT_SUGGESTIONS_STATE);
}
