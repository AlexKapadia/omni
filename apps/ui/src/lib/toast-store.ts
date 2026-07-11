/**
 * Minimal auto-dismissing toast queue for lightweight confirmations (a model
 * finished downloading, a folder path was copied…). Not for errors that need
 * a fix — those stay as inline copy in their own section.
 */
import { createStore, useStore, type StoreApi } from "zustand";

export type ToastVariant = "info" | "success" | "error";

export interface ToastItem {
  readonly id: string;
  readonly message: string;
  readonly variant: ToastVariant;
}

export interface ToastState {
  readonly toasts: readonly ToastItem[];
}

export const INITIAL_TOAST_STATE: ToastState = { toasts: [] };

export type ToastStore = StoreApi<ToastState>;

export function createToastStore(): ToastStore {
  return createStore<ToastState>(() => INITIAL_TOAST_STATE);
}

/** The one store the running app uses. Tests create their own via the factory. */
export const toastStore: ToastStore = createToastStore();

export function useToasts<T>(selector: (state: ToastState) => T): T {
  return useStore(toastStore, selector);
}

/** Keep the stack small — a few toasts, never a wall of past notices. */
const MAX_VISIBLE_TOASTS = 3;
const DEFAULT_AUTO_DISMISS_MS = 4000;

let nextToastId = 0;

/** Queue a toast; returns its id so a caller could dismiss it early. */
export function showToast(
  message: string,
  variant: ToastVariant = "info",
  store: ToastStore = toastStore,
  autoDismissMs: number = DEFAULT_AUTO_DISMISS_MS,
): string {
  nextToastId += 1;
  const id = `toast-${nextToastId}`;
  store.setState((state) => ({
    toasts: [...state.toasts, { id, message, variant }].slice(-MAX_VISIBLE_TOASTS),
  }));
  if (autoDismissMs > 0) {
    setTimeout(() => dismissToast(id, store), autoDismissMs);
  }
  return id;
}

export function dismissToast(id: string, store: ToastStore = toastStore): void {
  store.setState((state) => ({ toasts: state.toasts.filter((t) => t.id !== id) }));
}
