/**
 * Zustand store for the Library screen: the captured-meetings list, its load
 * lifecycle, and the search filter.
 *
 * Data arrives through the MeetingsRepository interface. Today the only
 * implementation is the MOCK generator (mock-meetings-repository.ts); the M2
 * engine-backed repository (SQLite meetings table over WS) implements the
 * same interface and swaps in without touching this store or the screen.
 */
import { createStore, useStore, type StoreApi } from "zustand";

export interface MeetingSummaryRow {
  readonly id: string;
  readonly title: string;
  /** One-line summary; empty string until the enhancement pipeline writes one. */
  readonly summary: string;
  /** ISO-8601 start time (local meetings, local clock). */
  readonly startIso: string;
  readonly durationMin: number;
}

/** The swappable data source. Mock now; engine repository in M2. */
export interface MeetingsRepository {
  listMeetings(): Promise<readonly MeetingSummaryRow[]>;
}

export type MeetingsLoadStatus = "loading" | "ready" | "error";

export interface MeetingsState {
  readonly status: MeetingsLoadStatus;
  readonly meetings: readonly MeetingSummaryRow[];
  readonly query: string;
  readonly errorMessage: string | null;
}

export const INITIAL_MEETINGS_STATE: MeetingsState = {
  status: "loading",
  meetings: [],
  query: "",
  errorMessage: null,
};

export type MeetingsStore = StoreApi<MeetingsState>;

export function createMeetingsStore(): MeetingsStore {
  return createStore<MeetingsState>(() => INITIAL_MEETINGS_STATE);
}

/** The one store the running app uses. Tests create their own via the factory. */
export const meetingsStore: MeetingsStore = createMeetingsStore();

export function useMeetings<T>(selector: (state: MeetingsState) => T): T {
  return useStore(meetingsStore, selector);
}

export async function loadMeetings(store: MeetingsStore, repository: MeetingsRepository): Promise<void> {
  store.setState({ status: "loading", errorMessage: null });
  try {
    const meetings = await repository.listMeetings();
    // Newest first — the library reads top-to-bottom back through time.
    const sorted = [...meetings].sort((a, b) => b.startIso.localeCompare(a.startIso));
    store.setState({ status: "ready", meetings: sorted });
  } catch (error) {
    store.setState({
      status: "error",
      errorMessage: error instanceof Error ? error.message : "Could not load meetings.",
    });
  }
}

export function setMeetingsQuery(store: MeetingsStore, query: string): void {
  store.setState({ query });
}

/**
 * Case-insensitive substring filter over title + summary. Pure and total:
 * whitespace-only queries match everything; regex metacharacters are literal
 * (plain substring, never a pattern — untrusted input stays untrusted).
 */
export function filterMeetings(
  meetings: readonly MeetingSummaryRow[],
  query: string,
): readonly MeetingSummaryRow[] {
  const needle = query.trim().toLowerCase();
  if (needle.length === 0) return meetings;
  return meetings.filter(
    (m) => m.title.toLowerCase().includes(needle) || m.summary.toLowerCase().includes(needle),
  );
}
