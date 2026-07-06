/**
 * Zustand store for the live-meeting notepad buffer.
 *
 * The user's rough notes are typed here during capture and later fused with
 * the transcript (M4 enhancement pipeline). The buffer survives screen
 * switches — leaving the live view must never lose a keystroke ("your lines
 * never move", and they never vanish either). Persistence to the vault is a
 * later milestone; this store is the single in-session source of truth.
 */
import { createStore, useStore, type StoreApi } from "zustand";

export interface NotepadState {
  /** The meeting the buffer belongs to; null before any capture. */
  readonly meetingId: string | null;
  readonly text: string;
}

export const INITIAL_NOTEPAD_STATE: NotepadState = { meetingId: null, text: "" };

export type NotepadStore = StoreApi<NotepadState>;

export function createNotepadStore(): NotepadStore {
  return createStore<NotepadState>(() => INITIAL_NOTEPAD_STATE);
}

/** The one store the running app uses. Tests create their own via the factory. */
export const notepadStore: NotepadStore = createNotepadStore();

export function useNotepad<T>(selector: (state: NotepadState) => T): T {
  return useStore(notepadStore, selector);
}

export function setNotepadText(store: NotepadStore, text: string): void {
  store.setState({ text });
}

/**
 * A new meeting gets a fresh page — but ONLY a different meeting. Re-entering
 * the same meeting (StrictMode remount, screen switch) keeps the buffer.
 */
export function bindNotepadToMeeting(store: NotepadStore, meetingId: string): void {
  const state = store.getState();
  if (state.meetingId === meetingId) return;
  store.setState({ meetingId, text: "" });
}
