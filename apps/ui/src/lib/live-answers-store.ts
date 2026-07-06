/**
 * Zustand store for live Answers-panel hits, fed by the engine's
 * `answers.hit` event (engine/ask/live_answers_spotter.py).
 *
 * WIRING (DEFERRED — orchestrator connects at reconciliation): the WS event
 * dispatcher calls applyAnswersHit(liveAnswersStore, envelope.payload) for
 * events named ANSWERS_HIT_EVENT_NAME, and clearLiveAnswers() when a new
 * capture starts (hits belong to one meeting).
 *
 * Security / honesty invariants:
 * - Fail-closed parse: a malformed payload is dropped whole — it never
 *   mutates the store (untrusted inbound frame rule).
 * - Duplicate and out-of-order deliveries are idempotent: a hit's identity
 *   is its normalised question; replays never duplicate panel entries.
 */
import { createStore, useStore, type StoreApi } from "zustand";

/** Event name pinned with the engine (engine/ask/__init__.py). */
export const ANSWERS_HIT_EVENT_NAME = "answers.hit";

/** Newest-first cap: the panel shows the top hit; history stays bounded. */
export const MAX_LIVE_ANSWER_HITS = 20;

export interface LiveAnswerHitSource {
  readonly notePath: string;
  readonly lineStart: number;
  readonly lineEnd: number;
  readonly headingPath: string;
  readonly snippet: string;
  readonly score: number;
}

export interface LiveAnswerHit {
  /** Stable identity (normalised question) — dedupe key and render key. */
  readonly id: string;
  readonly question: string;
  readonly askedBy: string;
  /** Engine-measured question-detection -> hits-ready span (<2 s budget). */
  readonly spottedToHitMs: number;
  readonly sources: readonly LiveAnswerHitSource[];
}

export interface LiveAnswersState {
  /** Newest first. Empty = the panel's honest idle state (renders nothing). */
  readonly hits: readonly LiveAnswerHit[];
}

export const INITIAL_LIVE_ANSWERS_STATE: LiveAnswersState = { hits: [] };

export type LiveAnswersStore = StoreApi<LiveAnswersState>;

export function createLiveAnswersStore(): LiveAnswersStore {
  return createStore<LiveAnswersState>(() => INITIAL_LIVE_ANSWERS_STATE);
}

/** The one store the running app uses. Tests create their own. */
export const liveAnswersStore: LiveAnswersStore = createLiveAnswersStore();

export function useLiveAnswers<T>(selector: (state: LiveAnswersState) => T): T {
  return useStore(liveAnswersStore, selector);
}

function isPlainObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isCount(value: unknown): value is number {
  return typeof value === "number" && Number.isInteger(value) && value >= 0;
}

function parseSource(value: unknown): LiveAnswerHitSource | null {
  if (!isPlainObject(value)) return null;
  const { note_path, line_start, line_end, heading_path, snippet, score } = value;
  if (typeof note_path !== "string" || note_path.length === 0) return null;
  if (!isCount(line_start) || line_start < 1) return null;
  if (!isCount(line_end) || line_end < line_start) return null;
  if (typeof heading_path !== "string" || typeof snippet !== "string") return null;
  if (typeof score !== "number" || !Number.isFinite(score)) return null;
  return {
    notePath: note_path,
    lineStart: line_start,
    lineEnd: line_end,
    headingPath: heading_path,
    snippet,
    score,
  };
}

/** Identity key: lowercased word tokens — punctuation/case immaterial. */
function normaliseQuestion(question: string): string {
  return (question.toLowerCase().match(/\w+/g) ?? []).join(" ");
}

/**
 * Validate one `answers.hit` payload against the pinned engine contract.
 * Returns null on ANY deviation (fail closed) — including zero sources,
 * because the engine never emits an empty hit.
 */
export function parseAnswersHitPayload(payload: unknown): LiveAnswerHit | null {
  if (!isPlainObject(payload)) return null;
  const { question, asked_by, spotted_to_hit_ms, hits } = payload;
  if (typeof question !== "string" || question.trim().length === 0) return null;
  if (typeof asked_by !== "string") return null;
  if (!isCount(spotted_to_hit_ms)) return null;
  if (!Array.isArray(hits) || hits.length === 0) return null;
  const sources: LiveAnswerHitSource[] = [];
  for (const raw of hits) {
    const source = parseSource(raw);
    if (source === null) return null; // one bad source poisons the payload
    sources.push(source);
  }
  return {
    id: normaliseQuestion(question),
    question: question.trim(),
    askedBy: asked_by,
    spottedToHitMs: spotted_to_hit_ms,
    sources,
  };
}

/** Apply one raw event payload: parse fail-closed, dedupe, prepend, cap. */
export function applyAnswersHit(store: LiveAnswersStore, payload: unknown): void {
  const hit = parseAnswersHitPayload(payload);
  if (hit === null) return; // fail closed: malformed frames change nothing
  store.setState((state) => {
    if (state.hits.some((existing) => existing.id === hit.id)) {
      return state; // duplicate/out-of-order replay: idempotent
    }
    return { hits: [hit, ...state.hits].slice(0, MAX_LIVE_ANSWER_HITS) };
  });
}

/** Wiring calls this when a new capture starts — hits belong to one meeting. */
export function clearLiveAnswers(store: LiveAnswersStore = liveAnswersStore): void {
  store.setState(INITIAL_LIVE_ANSWERS_STATE, true);
}
