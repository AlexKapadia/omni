/**
 * Rolling live summary from the engine's `summary.updated` event.
 */
import { createStore, useStore, type StoreApi } from "zustand";

export const SUMMARY_UPDATED_EVENT_NAME = "summary.updated";

export interface LiveSummaryState {
  readonly summaryMd: string;
  readonly updatedAtMs: number | null;
}

export const INITIAL_LIVE_SUMMARY_STATE: LiveSummaryState = {
  summaryMd: "",
  updatedAtMs: null,
};

export type LiveSummaryStore = StoreApi<LiveSummaryState>;

export function createLiveSummaryStore(): LiveSummaryStore {
  return createStore<LiveSummaryState>(() => INITIAL_LIVE_SUMMARY_STATE);
}

export const liveSummaryStore: LiveSummaryStore = createLiveSummaryStore();

export function useLiveSummary<T>(selector: (state: LiveSummaryState) => T): T {
  return useStore(liveSummaryStore, selector);
}

function isPlainObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

export function parseSummaryUpdatedPayload(payload: unknown): { summaryMd: string; updatedAtMs: number } | null {
  if (!isPlainObject(payload)) return null;
  const summary = payload["summary_md"];
  const updatedAt = payload["updated_at_ms"];
  if (typeof summary !== "string" || summary.length === 0) return null;
  if (typeof updatedAt !== "number" || !Number.isFinite(updatedAt)) return null;
  return { summaryMd: summary, updatedAtMs: updatedAt };
}

export function applySummaryUpdated(store: LiveSummaryStore, payload: unknown): void {
  const parsed = parseSummaryUpdatedPayload(payload);
  if (parsed === null) return;
  store.setState(parsed);
}

export function clearLiveSummary(store: LiveSummaryStore): void {
  store.setState(INITIAL_LIVE_SUMMARY_STATE);
}
