/**
 * TypeScript mirror of the FROZEN Naomi turn-loop surface — the additive
 * conversation commands/events on WS protocol v1 (engine source of truth:
 * engine/naomi/naomi_turn_protocol_names.py). Sits beside the existing
 * naomi-voice-protocol.ts (audio) — this file owns the turn control plane.
 *
 * Commands (UI → engine):
 *   naomi.listen.start { open_mic?: boolean }  open_mic=true keeps listening
 *                                              after each turn (VAD conversation);
 *                                              false = push-to-talk single utterance.
 *   naomi.listen.stop  { flush?: boolean }     flush=true forces the endpoint
 *                                              (ptt release); false discards → idle.
 * Events (engine → UI):
 *   naomi.state          { state, turn_id? }
 *   naomi.user_utterance { turn_id, text }            (VERBATIM — never rewritten)
 *   naomi.reply          { turn_id, text, affect?, citations[], no_answer, action_card_id? }
 *   naomi.turn.latency   { turn_id, endpoint_ms, retrieval_ms, llm_ms, ttfa_ms, total_ms }
 *   naomi.turn.error     { message, turn_id? }
 *
 * Security invariant: every inbound payload is untrusted — the parsers are
 * fail-closed (null on ANY deviation, never partial acceptance), matching the
 * house style in lib/protocol.ts and naomi-voice-protocol.ts.
 */

export const NAOMI_LISTEN_START_COMMAND_NAME = "naomi.listen.start";
export const NAOMI_LISTEN_STOP_COMMAND_NAME = "naomi.listen.stop";
export const NAOMI_STATE_EVENT_NAME = "naomi.state";
export const NAOMI_USER_UTTERANCE_EVENT_NAME = "naomi.user_utterance";
export const NAOMI_REPLY_EVENT_NAME = "naomi.reply";
export const NAOMI_TURN_LATENCY_EVENT_NAME = "naomi.turn.latency";
export const NAOMI_TURN_ERROR_EVENT_NAME = "naomi.turn.error";

/** The four turn-loop states the pool + captions key off. */
export const NAOMI_TURN_STATES = ["idle", "listening", "thinking", "speaking"] as const;
export type NaomiTurnState = (typeof NAOMI_TURN_STATES)[number];

export interface NaomiStateEvent {
  readonly state: NaomiTurnState;
  readonly turn_id: string | null;
}

export interface NaomiUserUtteranceEvent {
  readonly turn_id: string;
  /** Verbatim STT of the user's speech — the UI renders it as-is (fidelity mandate). */
  readonly text: string;
}

/** Affect triple carried on a reply (engine quantizes v/a; burst is a laugh or absent). */
export interface NaomiReplyAffect {
  readonly v: number;
  readonly a: number;
  readonly burst: "laugh" | null;
}

/** One cited source, copied verbatim from RetrievedChunk provenance (AskCitation). */
export interface NaomiReplyCitation {
  readonly n: number;
  readonly note_path: string;
  readonly line_start: number;
  readonly line_end: number;
  readonly heading_path: string;
  readonly quote: string;
}

export interface NaomiReplyEvent {
  readonly turn_id: string;
  readonly text: string;
  /** null when absent OR malformed/out-of-range (dropped, reply still kept). */
  readonly affect: NaomiReplyAffect | null;
  readonly no_answer: boolean;
  readonly citations: readonly NaomiReplyCitation[];
  readonly action_card_id: number | null;
}

export interface NaomiTurnLatencyEvent {
  readonly turn_id: string;
  readonly endpoint_ms: number;
  readonly retrieval_ms: number;
  readonly llm_ms: number;
  readonly ttfa_ms: number;
  readonly total_ms: number;
}

export interface NaomiTurnErrorEvent {
  readonly message: string;
  readonly turn_id: string | null;
}

// --- Outbound command builders (mirror the engine's pydantic defaults) ---

export function buildNaomiListenStartPayload(openMic: boolean): Record<string, unknown> {
  return { open_mic: openMic };
}

export function buildNaomiListenStopPayload(flush: boolean): Record<string, unknown> {
  return { flush };
}

// --- Fail-closed guards (same shapes as naomi-voice-protocol.ts) ---

function nonEmptyString(value: unknown, maxLength: number): value is string {
  return typeof value === "string" && value.length > 0 && value.length <= maxLength;
}

function boundedString(value: unknown, maxLength: number): value is string {
  // Allows the empty string (e.g. a root-level heading_path) but caps length
  // so a hostile frame can never flood the UI with an unbounded field.
  return typeof value === "string" && value.length <= maxLength;
}

function finiteNumber(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

function nonNegativeInteger(value: unknown): value is number {
  return finiteNumber(value) && Number.isInteger(value) && value >= 0;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isTurnState(value: unknown): value is NaomiTurnState {
  return typeof value === "string" && (NAOMI_TURN_STATES as readonly string[]).includes(value);
}

const MAX_TURN_ID = 128;
const MAX_UTTERANCE_CHARS = 10_000;
const MAX_REPLY_CHARS = 10_000;
const MAX_ERROR_CHARS = 2_000;
const MAX_PATH_CHARS = 1_024;
const MAX_QUOTE_CHARS = 4_000;

export function parseNaomiStatePayload(payload: Record<string, unknown>): NaomiStateEvent | null {
  const state = payload["state"];
  const turnId = payload["turn_id"];
  if (!isTurnState(state)) return null; // unknown state string → fail closed
  if (turnId !== undefined && turnId !== null && !nonEmptyString(turnId, MAX_TURN_ID)) return null;
  return { state, turn_id: nonEmptyString(turnId, MAX_TURN_ID) ? turnId : null };
}

export function parseNaomiUserUtterancePayload(
  payload: Record<string, unknown>,
): NaomiUserUtteranceEvent | null {
  const turnId = payload["turn_id"];
  const text = payload["text"];
  if (!nonEmptyString(turnId, MAX_TURN_ID)) return null;
  if (!nonEmptyString(text, MAX_UTTERANCE_CHARS)) return null;
  return { turn_id: turnId, text };
}

/** Parse one citation member; null on ANY deviation (caller rejects the reply). */
function parseCitationMember(value: unknown): NaomiReplyCitation | null {
  if (!isRecord(value)) return null;
  const n = value["n"];
  const notePath = value["note_path"];
  const lineStart = value["line_start"];
  const lineEnd = value["line_end"];
  const headingPath = value["heading_path"];
  const quote = value["quote"];
  // n and line numbers are 1-based inclusive integers (AskCitation contract).
  if (!(nonNegativeInteger(n) && n >= 1)) return null;
  if (!nonEmptyString(notePath, MAX_PATH_CHARS)) return null;
  if (!(nonNegativeInteger(lineStart) && lineStart >= 1)) return null;
  if (!(nonNegativeInteger(lineEnd) && lineEnd >= 1)) return null;
  if (!boundedString(headingPath, MAX_PATH_CHARS)) return null;
  if (!boundedString(quote, MAX_QUOTE_CHARS)) return null;
  return {
    n,
    note_path: notePath,
    line_start: lineStart,
    line_end: lineEnd,
    heading_path: headingPath,
    quote,
  };
}

/**
 * Parse the optional reply affect LENIENTLY: any problem (absent, malformed,
 * out of range v∈[-1,1] / a∈[0,1], unknown burst) yields null — the affect is
 * dropped but the reply itself is still delivered (spec: keep the reply).
 */
function parseReplyAffectLenient(value: unknown): NaomiReplyAffect | null {
  if (!isRecord(value)) return null;
  const v = value["v"];
  const a = value["a"];
  const burst = value["burst"];
  if (!finiteNumber(v) || v < -1 || v > 1) return null;
  if (!finiteNumber(a) || a < 0 || a > 1) return null;
  if (burst !== undefined && burst !== null && burst !== "laugh") return null;
  return { v, a, burst: burst === "laugh" ? "laugh" : null };
}

export function parseNaomiReplyPayload(payload: Record<string, unknown>): NaomiReplyEvent | null {
  const turnId = payload["turn_id"];
  const text = payload["text"];
  const noAnswer = payload["no_answer"];
  const citationsRaw = payload["citations"];
  const actionCardId = payload["action_card_id"];
  if (!nonEmptyString(turnId, MAX_TURN_ID)) return null;
  if (!nonEmptyString(text, MAX_REPLY_CHARS)) return null;
  if (typeof noAnswer !== "boolean") return null; // honesty flag must be exact
  if (!Array.isArray(citationsRaw)) return null;
  const citations: NaomiReplyCitation[] = [];
  for (const member of citationsRaw) {
    const parsed = parseCitationMember(member);
    if (parsed === null) return null; // a malformed member corrupts the whole reply
    citations.push(parsed);
  }
  const hasCard = actionCardId !== undefined && actionCardId !== null;
  if (hasCard && !(nonNegativeInteger(actionCardId) && actionCardId >= 1)) return null;
  return {
    turn_id: turnId,
    text,
    affect: parseReplyAffectLenient(payload["affect"]),
    no_answer: noAnswer,
    citations,
    action_card_id: hasCard ? (actionCardId as number) : null,
  };
}

export function parseNaomiTurnLatencyPayload(
  payload: Record<string, unknown>,
): NaomiTurnLatencyEvent | null {
  const turnId = payload["turn_id"];
  if (!nonEmptyString(turnId, MAX_TURN_ID)) return null;
  const endpoint = payload["endpoint_ms"];
  const retrieval = payload["retrieval_ms"];
  const llm = payload["llm_ms"];
  const ttfa = payload["ttfa_ms"];
  const total = payload["total_ms"];
  // Latency spans are non-negative integer milliseconds (engine measures ints).
  if (!nonNegativeInteger(endpoint)) return null;
  if (!nonNegativeInteger(retrieval)) return null;
  if (!nonNegativeInteger(llm)) return null;
  if (!nonNegativeInteger(ttfa)) return null;
  if (!nonNegativeInteger(total)) return null;
  return {
    turn_id: turnId,
    endpoint_ms: endpoint,
    retrieval_ms: retrieval,
    llm_ms: llm,
    ttfa_ms: ttfa,
    total_ms: total,
  };
}

export function parseNaomiTurnErrorPayload(
  payload: Record<string, unknown>,
): NaomiTurnErrorEvent | null {
  const message = payload["message"];
  const turnId = payload["turn_id"];
  if (!nonEmptyString(message, MAX_ERROR_CHARS)) return null;
  if (turnId !== undefined && turnId !== null && !nonEmptyString(turnId, MAX_TURN_ID)) return null;
  return { message, turn_id: nonEmptyString(turnId, MAX_TURN_ID) ? turnId : null };
}
