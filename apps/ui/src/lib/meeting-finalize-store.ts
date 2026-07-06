/**
 * Zustand store for the post-capture "Finalize meeting" flow on the live
 * screen: idle -> pending -> ready | failed, driven by the meeting.finalize
 * reply (authoritative) and refined by the engine's enhance.started /
 * enhance.ready / enhance.failed progress events.
 *
 * Honesty invariants:
 * - No state is faked: pending only after the command was actually sent,
 *   ready only from a real reply/event carrying the real note path, failed
 *   with the engine's own plain-voice reason.
 * - Events for a DIFFERENT meeting id never mutate this flow (stale-event
 *   defence, mirroring the transcript store's discipline).
 */
import { createStore, useStore, type StoreApi } from "zustand";
import { requestMeetingFinalize } from "./meetings-live-repository";

/** Event names pinned with the engine (meeting_finalization_payloads.py). */
export const ENHANCE_STARTED_EVENT_NAME = "enhance.started";
export const ENHANCE_READY_EVENT_NAME = "enhance.ready";
export const ENHANCE_FAILED_EVENT_NAME = "enhance.failed";

export type FinalizeStatus = "idle" | "pending" | "ready" | "failed";

export interface MeetingFinalizeState {
  readonly status: FinalizeStatus;
  /** The meeting this flow belongs to; null before any finalize. */
  readonly meetingId: string | null;
  /** Vault-relative note path once ready. */
  readonly notePath: string | null;
  /** Honest failure copy (engine's own reason) when failed. */
  readonly errorMessage: string | null;
  /** Non-fatal warnings the engine reported alongside a ready result. */
  readonly warnings: readonly string[];
}

export const INITIAL_MEETING_FINALIZE_STATE: MeetingFinalizeState = {
  status: "idle",
  meetingId: null,
  notePath: null,
  errorMessage: null,
  warnings: [],
};

export type MeetingFinalizeStore = StoreApi<MeetingFinalizeState>;

export function createMeetingFinalizeStore(): MeetingFinalizeStore {
  return createStore<MeetingFinalizeState>(() => INITIAL_MEETING_FINALIZE_STATE);
}

/** The one store the running app uses. Tests create their own. */
export const meetingFinalizeStore: MeetingFinalizeStore = createMeetingFinalizeStore();

export function useMeetingFinalize<T>(selector: (state: MeetingFinalizeState) => T): T {
  return useStore(meetingFinalizeStore, selector);
}

/** A new capture means a new meeting: any previous flow is over. */
export function resetMeetingFinalize(
  store: MeetingFinalizeStore = meetingFinalizeStore,
): void {
  store.setState(INITIAL_MEETING_FINALIZE_STATE, true);
}

export type FinalizeRequestFn = typeof requestMeetingFinalize;

/**
 * Send meeting.finalize with the notepad buffer (verbatim — the engine
 * stores the exact bytes) and drive the store through the honest states.
 */
export async function finalizeMeeting(
  meetingId: string,
  notepadText: string,
  store: MeetingFinalizeStore = meetingFinalizeStore,
  request: FinalizeRequestFn = requestMeetingFinalize,
): Promise<void> {
  if (store.getState().status === "pending") return; // one flow at a time
  store.setState({
    status: "pending",
    meetingId,
    notePath: null,
    errorMessage: null,
    warnings: [],
  });
  try {
    const outcome = await request(meetingId, notepadText);
    store.setState((state) => {
      if (state.meetingId !== meetingId) return state; // a newer flow took over
      return {
        ...state,
        status: "ready",
        notePath: outcome.notePath,
        warnings: outcome.warnings,
        errorMessage: null,
      };
    });
  } catch (error) {
    store.setState((state) => {
      if (state.meetingId !== meetingId) return state;
      return {
        ...state,
        status: "failed",
        errorMessage: error instanceof Error ? error.message : "finalize failed",
      };
    });
  }
}

function isPlainObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function payloadMeetingId(payload: unknown): string | null {
  if (!isPlainObject(payload)) return null;
  const id = payload["meeting_id"];
  return typeof id === "string" && id.length > 0 ? id : null;
}

/** enhance.ready may beat the reply — treat it as authoritative success. */
export function applyEnhanceReady(store: MeetingFinalizeStore, payload: unknown): void {
  const meetingId = payloadMeetingId(payload);
  if (meetingId === null || !isPlainObject(payload)) return;
  const notePath = payload["note_path"];
  if (typeof notePath !== "string" || notePath.length === 0) return;
  store.setState((state) => {
    if (state.meetingId !== meetingId || state.status !== "pending") return state;
    return { ...state, status: "ready", notePath, errorMessage: null };
  });
}

/** enhance.failed while pending: surface the engine's honest reason. */
export function applyEnhanceFailed(store: MeetingFinalizeStore, payload: unknown): void {
  const meetingId = payloadMeetingId(payload);
  if (meetingId === null || !isPlainObject(payload)) return;
  const reason = payload["reason"];
  if (typeof reason !== "string" || reason.length === 0) return;
  store.setState((state) => {
    if (state.meetingId !== meetingId || state.status !== "pending") return state;
    return { ...state, status: "failed", errorMessage: reason };
  });
}
