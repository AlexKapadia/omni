/**
 * Zustand store for Ask Omni: question lifecycle, the answer with its
 * citations, and which source is expanded.
 *
 * Answers arrive through the AskAnswerProvider interface. The REAL
 * implementation (engine-ask-answer-provider.ts) speaks the engine's
 * `ask.query` command over the WS transport; it parses the M3 pipeline's
 * reply fail-closed into this shape.
 *
 * Citation shape is pinned by docs/research/m3-retrieval-architecture-
 * recommendation.md §Cite: every chunk carries note_path + line range +
 * heading_path — the UI renders exactly that, never a vague "source".
 * Latency is the engine-measured breakdown, rendered verbatim under the
 * answer (speed is a showcase feature — session mandate).
 */
import { createStore, useStore, type StoreApi } from "zustand";

export interface AskCitation {
  /** 1-based marker as rendered inline: [1], [2] … */
  readonly marker: number;
  readonly notePath: string;
  readonly lineStart: number;
  readonly lineEnd: number;
  /** Heading breadcrumb inside the note, e.g. "Northwind › Renewal". */
  readonly headingPath: string;
  /** The cited chunk text, verbatim. */
  readonly snippet: string;
}

/** One run of answer prose. Structured spans — never raw HTML from a model. */
export interface AskProseSpan {
  readonly text: string;
  /** Key fact emphasis (<strong> in the design). */
  readonly strong?: boolean;
  /** Inline citation marker rendered after this span. */
  readonly citationMarker?: number;
}

/** Engine-measured spans, ms, exact: total is retrieval + synthesis. */
export interface AskLatencyBreakdown {
  readonly retrievalMs: number;
  readonly synthesisMs: number;
  readonly totalMs: number;
}

export interface AskAnswer {
  readonly headline: string;
  readonly prose: readonly AskProseSpan[];
  readonly citations: readonly AskCitation[];
  /** Present on real engine answers; rendered mono under the answer. */
  readonly latency?: AskLatencyBreakdown;
}

/** The swappable answer source. Mock now; M3 retrieval pipeline later. */
export interface AskAnswerProvider {
  answer(question: string): Promise<AskAnswer>;
}

export type AskStatus = "empty" | "thinking" | "answered" | "error";

export interface AskState {
  readonly status: AskStatus;
  readonly question: string;
  readonly answer: AskAnswer | null;
  readonly errorMessage: string | null;
  /** Which citation's source detail is expanded; null = none. */
  readonly openCitationMarker: number | null;
  /** Monotonic request id — a stale response must never clobber a newer one. */
  readonly requestSeq: number;
}

export const INITIAL_ASK_STATE: AskState = {
  status: "empty",
  question: "",
  answer: null,
  errorMessage: null,
  openCitationMarker: null,
  requestSeq: 0,
};

export type AskStore = StoreApi<AskState>;

export function createAskStore(): AskStore {
  return createStore<AskState>(() => INITIAL_ASK_STATE);
}

/** The one store the running app uses. Tests create their own via the factory. */
export const askStore: AskStore = createAskStore();

export function useAsk<T>(selector: (state: AskState) => T): T {
  return useStore(askStore, selector);
}

export async function askQuestion(
  store: AskStore,
  provider: AskAnswerProvider,
  question: string,
): Promise<void> {
  const trimmed = question.trim();
  if (trimmed.length === 0) return; // nothing asked, nothing done
  const seq = store.getState().requestSeq + 1;
  store.setState({
    status: "thinking",
    question: trimmed,
    answer: null,
    errorMessage: null,
    openCitationMarker: null,
    requestSeq: seq,
  });
  try {
    const answer = await provider.answer(trimmed);
    // Out-of-order guard: only the latest request may write the answer.
    if (store.getState().requestSeq !== seq) return;
    store.setState({ status: "answered", answer });
  } catch (error) {
    if (store.getState().requestSeq !== seq) return;
    store.setState({
      status: "error",
      errorMessage: error instanceof Error ? error.message : "Could not answer that.",
    });
  }
}

/** Toggle a citation's source detail open/closed. */
export function toggleCitation(store: AskStore, marker: number): void {
  store.setState((state) => ({
    openCitationMarker: state.openCitationMarker === marker ? null : marker,
  }));
}
