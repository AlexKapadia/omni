/**
 * Live translation lines from translation.updated events.
 */
import { createStore, useStore, type StoreApi } from "zustand";

export const TRANSLATION_UPDATED_EVENT_NAME = "translation.updated";

export interface TranslationLine {
  readonly stream: "me" | "them";
  readonly text: string;
}

export interface LiveTranslationState {
  readonly lines: readonly TranslationLine[];
}

export const INITIAL_LIVE_TRANSLATION_STATE: LiveTranslationState = { lines: [] };

export type LiveTranslationStore = StoreApi<LiveTranslationState>;

export function createLiveTranslationStore(): LiveTranslationStore {
  return createStore<LiveTranslationState>(() => INITIAL_LIVE_TRANSLATION_STATE);
}

export const liveTranslationStore: LiveTranslationStore = createLiveTranslationStore();

export function useLiveTranslation<T>(selector: (state: LiveTranslationState) => T): T {
  return useStore(liveTranslationStore, selector);
}

function parseLine(raw: unknown): TranslationLine | null {
  if (typeof raw !== "object" || raw === null) return null;
  const stream = (raw as Record<string, unknown>)["stream"];
  const text = (raw as Record<string, unknown>)["text"];
  if ((stream !== "me" && stream !== "them") || typeof text !== "string" || text.length === 0) {
    return null;
  }
  return { stream, text };
}

export function applyTranslationUpdated(
  store: LiveTranslationStore,
  payload: Record<string, unknown>,
): void {
  const rawLines = payload["lines"];
  if (!Array.isArray(rawLines)) return;
  const lines: TranslationLine[] = [];
  for (const item of rawLines) {
    const line = parseLine(item);
    if (line !== null) lines.push(line);
  }
  if (lines.length === 0) return;
  store.setState({ lines });
}

export function clearLiveTranslation(store: LiveTranslationStore): void {
  store.setState(INITIAL_LIVE_TRANSLATION_STATE);
}
