/**
 * TypeScript mirror of the Naomi voice event/command surface — additive
 * names on WS protocol v1 (engine side: engine/voice/naomi_voice_event_payloads.py).
 *
 * Events (engine → UI):
 *   naomi.audio.chunk         { context_id, seq, pcm_b64, sample_rate, ttfa_ms? }
 *   naomi.audio.done          { context_id, reason: "completed"|"cancelled"|"error", detail? }
 *   naomi.speaking.timestamps { context_id, words: string[], starts_s: number[], ends_s: number[] }
 * Commands (UI → engine):
 *   naomi.say    { text, affect?: { v, a, burst? } }
 *   naomi.cancel { }
 *
 * Security invariant: every payload is untrusted input — parsers are
 * fail-closed (null on ANY deviation, never partial acceptance), matching
 * the house style in lib/protocol.ts.
 */

export const NAOMI_AUDIO_CHUNK_EVENT_NAME = "naomi.audio.chunk";
export const NAOMI_AUDIO_DONE_EVENT_NAME = "naomi.audio.done";
export const NAOMI_SPEAKING_TIMESTAMPS_EVENT_NAME = "naomi.speaking.timestamps";
export const NAOMI_SAY_COMMAND_NAME = "naomi.say";
export const NAOMI_CANCEL_COMMAND_NAME = "naomi.cancel";

export interface NaomiAudioChunkPayload {
  readonly context_id: string;
  readonly seq: number;
  readonly pcm_b64: string;
  readonly sample_rate: number;
  /** Present on seq 0 only: measured ms from say-dispatch to first audio. */
  readonly ttfa_ms: number | null;
}

export type NaomiDoneReason = "completed" | "cancelled" | "error";

export interface NaomiAudioDonePayload {
  readonly context_id: string;
  readonly reason: NaomiDoneReason;
  readonly detail: string | null;
}

export interface NaomiSpeakingTimestampsPayload {
  readonly context_id: string;
  readonly words: readonly string[];
  readonly starts_s: readonly number[];
  readonly ends_s: readonly number[];
}

function nonEmptyString(value: unknown, maxLength: number): value is string {
  return typeof value === "string" && value.length > 0 && value.length <= maxLength;
}

function finiteNumber(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

export function parseNaomiAudioChunkPayload(
  payload: Record<string, unknown>,
): NaomiAudioChunkPayload | null {
  const contextId = payload["context_id"];
  const seq = payload["seq"];
  const pcm = payload["pcm_b64"];
  const rate = payload["sample_rate"];
  const ttfa = payload["ttfa_ms"];
  if (!nonEmptyString(contextId, 128)) return null;
  if (!finiteNumber(seq) || seq < 0 || !Number.isInteger(seq)) return null;
  if (typeof pcm !== "string" || pcm.length === 0) return null;
  if (!finiteNumber(rate) || rate <= 0) return null;
  if (ttfa !== undefined && ttfa !== null && (!finiteNumber(ttfa) || ttfa < 0)) return null;
  return {
    context_id: contextId,
    seq,
    pcm_b64: pcm,
    sample_rate: rate,
    ttfa_ms: typeof ttfa === "number" ? ttfa : null,
  };
}

export function parseNaomiAudioDonePayload(
  payload: Record<string, unknown>,
): NaomiAudioDonePayload | null {
  const contextId = payload["context_id"];
  const reason = payload["reason"];
  const detail = payload["detail"];
  if (!nonEmptyString(contextId, 128)) return null;
  if (reason !== "completed" && reason !== "cancelled" && reason !== "error") return null;
  if (detail !== undefined && detail !== null && typeof detail !== "string") return null;
  return { context_id: contextId, reason, detail: typeof detail === "string" ? detail : null };
}

export function parseNaomiSpeakingTimestampsPayload(
  payload: Record<string, unknown>,
): NaomiSpeakingTimestampsPayload | null {
  const contextId = payload["context_id"];
  const words = payload["words"];
  const starts = payload["starts_s"];
  const ends = payload["ends_s"];
  if (!nonEmptyString(contextId, 128)) return null;
  if (!Array.isArray(words) || !Array.isArray(starts) || !Array.isArray(ends)) return null;
  // The three arrays are index-aligned by contract — mismatched lengths
  // mean a corrupt frame, not a usable one (fail closed).
  if (words.length !== starts.length || words.length !== ends.length) return null;
  if (!words.every((w) => typeof w === "string")) return null;
  if (!starts.every((s) => finiteNumber(s) && s >= 0)) return null;
  if (!ends.every((e) => finiteNumber(e) && e >= 0)) return null;
  return {
    context_id: contextId,
    words: words as string[],
    starts_s: starts as number[],
    ends_s: ends as number[],
  };
}

/** Affect wire shape for naomi.say (engine quantizes for Cartesia). */
export interface NaomiSayAffect {
  readonly v: number;
  readonly a: number;
  readonly burst: "laugh" | null;
}

export function buildNaomiSayPayload(
  text: string,
  affect: NaomiSayAffect | null,
): Record<string, unknown> {
  return affect === null
    ? { text }
    : { text, affect: { v: affect.v, a: affect.a, burst: affect.burst } };
}
