/**
 * Coordinates the app's coachmark queue (redesign-brief-v2.md §5.2): every
 * mounted coachmark registers itself by id; at most ONE is visible app-wide
 * at a time (first-registered wins); dismissing the visible one lets the
 * next queued coachmark take its turn. Dismissal is permanent and persisted
 * to localStorage so each coachmark is "shown once" per the brief's
 * discoverability contract, not once per session.
 *
 * WHERE in the pipeline: consumed by useCoachmark() below and by
 * <Coachmark id> (components/coachmark.tsx). Written only through the
 * exported functions — components never call store.setState directly.
 */
import { useEffect } from "react";
import { createStore, useStore, type StoreApi } from "zustand";

const STORAGE_KEY = "omni.coachmarks.v1";

interface CoachmarkState {
  /** Ids the user has permanently dismissed. */
  readonly dismissed: ReadonlySet<string>;
  /** Registration order of currently-mounted, not-yet-dismissed coachmarks.
   * The head of this queue is the one visible coachmark. */
  readonly queue: readonly string[];
}

/**
 * Reads the persisted dismissed-id set. Fails closed to an empty set on any
 * parse error or non-array shape — corrupted/tampered storage must never
 * crash the app, and the conservative UX choice is "show nothing extra"
 * (i.e. behave as if nothing was ever dismissed) rather than guessing at a
 * partially-recovered set.
 */
function readDismissed(): ReadonlySet<string> {
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (raw === null) return new Set();
    const parsed: unknown = JSON.parse(raw);
    if (!Array.isArray(parsed)) return new Set();
    return new Set(parsed.filter((entry): entry is string => typeof entry === "string"));
  } catch {
    return new Set();
  }
}

function persistDismissed(dismissed: ReadonlySet<string>): void {
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify([...dismissed]));
  } catch {
    // Fail-safe: a full/blocked localStorage must not crash the dismiss
    // flow. Worst case the coachmark reappears next launch, which is far
    // less harmful than throwing mid-render.
  }
}

export type CoachmarkStore = StoreApi<CoachmarkState>;

/** Factory so tests get an isolated store instead of sharing mutable module
 * state (mirrors engine-status-store.ts's pattern). */
export function createCoachmarkStore(): CoachmarkStore {
  return createStore<CoachmarkState>(() => ({
    dismissed: readDismissed(),
    queue: [],
  }));
}

/** The one store the running app uses. */
export const coachmarkStore: CoachmarkStore = createCoachmarkStore();

/** Registers a coachmark id into the queue. No-op (idempotent) if already
 * dismissed or already queued, since React effects can re-fire (StrictMode
 * double-invoke, remounts). */
function register(store: CoachmarkStore, id: string): void {
  const state = store.getState();
  if (state.dismissed.has(id) || state.queue.includes(id)) return;
  store.setState({ queue: [...state.queue, id] });
}

/** Removes a coachmark id from the queue WITHOUT dismissing it — e.g. its
 * owning component unmounted before the user saw it, so it is free to queue
 * again next time it mounts. */
function unregister(store: CoachmarkStore, id: string): void {
  const state = store.getState();
  if (!state.queue.includes(id)) return;
  store.setState({ queue: state.queue.filter((queuedId) => queuedId !== id) });
}

/**
 * Permanently dismisses a coachmark: removed from the queue AND recorded in
 * the persisted dismissed set, so it never shows again. Idempotent — a
 * double-dismiss (e.g. a fast double-click on "Got it", or two components
 * racing) is a safe no-op on the second call rather than a duplicate write.
 */
function dismiss(store: CoachmarkStore, id: string): void {
  const state = store.getState();
  if (state.dismissed.has(id)) return; // already dismissed — nothing to do
  const dismissed = new Set(state.dismissed);
  dismissed.add(id);
  persistDismissed(dismissed);
  store.setState({ dismissed, queue: state.queue.filter((queuedId) => queuedId !== id) });
}

export interface UseCoachmarkResult {
  /** True only when this id is both un-dismissed AND at the head of the
   * queue — the one coachmark currently allowed to render. */
  readonly visible: boolean;
  /** Permanently dismisses this coachmark and lets the next queued one show. */
  readonly dismiss: () => void;
}

/**
 * React hook: registers `id` on mount, unregisters on unmount, and reports
 * whether it is this coachmark's turn to be visible. Call once per
 * coachmark id (normally from inside <Coachmark id=...>, never directly by
 * screen code).
 */
export function useCoachmark(id: string, store: CoachmarkStore = coachmarkStore): UseCoachmarkResult {
  useEffect(() => {
    register(store, id);
    return () => unregister(store, id);
    // `store` is a stable identity by contract (factory-created once, passed
    // down or defaulted to the module singleton) — depending on [id, store]
    // is correct and never thrashes the queue on unrelated re-renders.
  }, [id, store]);

  const isDismissed = useStore(store, (s) => s.dismissed.has(id));
  const isHeadOfQueue = useStore(store, (s) => s.queue[0] === id);

  return {
    visible: !isDismissed && isHeadOfQueue,
    dismiss: () => dismiss(store, id),
  };
}
