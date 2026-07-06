/**
 * Zustand store for the Library's meeting-detail pane: which meeting is
 * open, its load lifecycle, and the finalize ("Enhance now") action state.
 *
 * Data access is injected (DetailLoader / MeetingFinalizer from
 * meetings-live-repository) so tests drive the store with fakes. A stale
 * guard drops responses that arrive after the user switched meetings —
 * detail for meeting A must never render under meeting B's header.
 */
import { createStore, useStore, type StoreApi } from "zustand";
import type { FinalizeOutcome, MeetingDetail } from "./meetings-live-repository";

export type MeetingsDetailStatus = "loading" | "ready" | "error";

export interface MeetingsDetailState {
  /** Meeting the pane is showing; null = pane closed. */
  readonly selectedId: string | null;
  readonly status: MeetingsDetailStatus;
  readonly detail: MeetingDetail | null;
  readonly errorMessage: string | null;
  readonly finalizing: boolean;
  /** Outcome line after a finalize attempt (success or honest failure). */
  readonly finalizeMessage: string | null;
}

export const INITIAL_MEETINGS_DETAIL_STATE: MeetingsDetailState = {
  selectedId: null,
  status: "loading",
  detail: null,
  errorMessage: null,
  finalizing: false,
  finalizeMessage: null,
};

export type MeetingsDetailStore = StoreApi<MeetingsDetailState>;

export function createMeetingsDetailStore(): MeetingsDetailStore {
  return createStore<MeetingsDetailState>(() => INITIAL_MEETINGS_DETAIL_STATE);
}

/** The one store the running app uses. Tests create their own. */
export const meetingsDetailStore: MeetingsDetailStore = createMeetingsDetailStore();

export function useMeetingsDetail<T>(selector: (state: MeetingsDetailState) => T): T {
  return useStore(meetingsDetailStore, selector);
}

export function openMeetingDetail(store: MeetingsDetailStore, meetingId: string): void {
  store.setState({
    ...INITIAL_MEETINGS_DETAIL_STATE,
    selectedId: meetingId,
    status: "loading",
  });
}

export function closeMeetingDetail(store: MeetingsDetailStore): void {
  store.setState(INITIAL_MEETINGS_DETAIL_STATE, true);
}

export async function loadMeetingDetail(
  store: MeetingsDetailStore,
  load: (meetingId: string) => Promise<MeetingDetail>,
  meetingId: string,
): Promise<void> {
  store.setState({ status: "loading", errorMessage: null, detail: null });
  try {
    const detail = await load(meetingId);
    // Stale guard: the user may have switched meetings while we waited.
    if (store.getState().selectedId !== meetingId) return;
    store.setState({ status: "ready", detail });
  } catch (error) {
    if (store.getState().selectedId !== meetingId) return;
    store.setState({
      status: "error",
      errorMessage: error instanceof Error ? error.message : "Could not load the meeting.",
    });
  }
}

export async function runMeetingFinalize(
  store: MeetingsDetailStore,
  finalize: (meetingId: string, notepadText: string) => Promise<FinalizeOutcome>,
  reloadDetail: (meetingId: string) => Promise<MeetingDetail>,
  meetingId: string,
  notepadText: string,
  onFinalized: () => void,
): Promise<void> {
  store.setState({ finalizing: true, finalizeMessage: null });
  try {
    const outcome = await finalize(meetingId, notepadText);
    if (store.getState().selectedId !== meetingId) return;
    // Honest outcome line: partial success is reported as exactly that.
    const message = outcome.enhanceOk
      ? `Enhanced notes saved to ${outcome.notePath}.`
      : `Note saved to ${outcome.notePath}, but enhancement was unavailable — your raw notes are safe.`;
    store.setState({ finalizing: false, finalizeMessage: message });
    onFinalized();
    await loadMeetingDetail(store, reloadDetail, meetingId); // fresh regions
  } catch (error) {
    if (store.getState().selectedId !== meetingId) return;
    store.setState({
      finalizing: false,
      finalizeMessage:
        error instanceof Error ? error.message : "The engine refused the finalize request.",
    });
  }
}
