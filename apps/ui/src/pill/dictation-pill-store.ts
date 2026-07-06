/**
 * Zustand store wrapping the pure pill reducer — the single source of truth
 * for the pill window. Tests drive the reducer directly; the store exists
 * only to bind React to it.
 */
import { createStore, useStore, type StoreApi } from "zustand";

import {
  IDLE_PILL_STATE,
  reduceDictationPill,
  type DictationPillEvent,
  type DictationPillState,
} from "./dictation-pill-state";

export type DictationPillStore = StoreApi<DictationPillState>;

export function createDictationPillStore(): DictationPillStore {
  return createStore<DictationPillState>(() => IDLE_PILL_STATE);
}

/** The one store the running pill uses. Tests create their own. */
export const dictationPillStore: DictationPillStore = createDictationPillStore();

export function dispatchPillEvent(store: DictationPillStore, event: DictationPillEvent): void {
  // replace=true: phases are a discriminated union — merging would leak
  // fields from a previous phase into the next one.
  store.setState(reduceDictationPill(store.getState(), event), true);
}

export function usePillState<T>(selector: (state: DictationPillState) => T): T {
  return useStore(dictationPillStore, selector);
}
