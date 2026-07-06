/**
 * TypeScript mirror of the M5 dictation additions to WS protocol v1.
 *
 * Mirrors engine/dictation/dictation_protocol_names.py EXACTLY (names and
 * payload shapes are pinned by the engine). Additive companion to
 * lib/protocol.ts — the envelope is parsed there; this file validates the
 * per-event payloads.
 *
 * Security invariant: every payload is untrusted input. Every parser is
 * fail-closed — any deviation from the pinned shape returns null, never a
 * partially-coerced object.
 */

// --- message names (pinned, dot-namespaced) ---
export const DICTATION_BEGIN_COMMAND_NAME = "dictation.begin";
export const DICTATION_END_COMMAND_NAME = "dictation.end";
export const DICTATION_PARTIAL_EVENT_NAME = "dictation.partial";
export const DICTATION_FINAL_EVENT_NAME = "dictation.final";
export const DICTATION_ERROR_EVENT_NAME = "dictation.error";

/**
 * Pinned by engine DictationMode — "note" is the safe default path.
 * "inject" = UI-requested disposition (external app focused at keydown):
 * the shell pastes cleaned_text into that app; nothing else is written.
 */
export type DictationMode = "note" | "command" | "inject";

/** Pinned by the dictation_intents CHECK constraint. */
export type DictationIntentType =
  | "create_event"
  | "upsert_contact"
  | "draft_email"
  | "write_note"
  | "unknown";

export interface DictationIntentPayload {
  readonly intent_type: DictationIntentType;
  readonly fields: Readonly<Record<string, unknown>>;
  readonly confidence: number; // 0..1
}

export interface DictationPartialPayload {
  readonly text: string; // verbatim transcript-so-far
}

export interface DictationFinalPayload {
  readonly mode: DictationMode;
  readonly text: string; // RAW verbatim transcript (ground truth, always)
  readonly note_path?: string;
  readonly note_title?: string;
  readonly title_source?: string; // "model" | "fallback"
  readonly intent?: DictationIntentPayload; // recorded only — NEVER executed
  readonly degraded_reason?: string; // honest partial-failure note
  readonly cleaned_text?: string; // faithfulness-guarded cleanup (== raw on fallback)
  readonly cleanup_source?: string; // "model" | "raw_fallback"
  readonly cleanup_latency_ms?: number; // real measured ms (speed showcase)
  readonly flush_ms?: number; // STT flush ms, wiring-measured
}

export interface DictationErrorPayload {
  readonly reason: string;
}

const INTENT_TYPES: ReadonlySet<string> = new Set([
  "create_event",
  "upsert_contact",
  "draft_email",
  "write_note",
  "unknown",
]);

function isPlainObject(value: unknown): value is Record<string, unknown> {
  if (typeof value !== "object" || value === null || Array.isArray(value)) return false;
  const proto: unknown = Object.getPrototypeOf(value);
  return proto === Object.prototype || proto === null;
}

export function parseDictationPartialPayload(
  payload: Record<string, unknown>,
): DictationPartialPayload | null {
  const { text } = payload;
  if (typeof text !== "string") return null; // empty string IS valid (silence)
  return { text };
}

function parseIntent(value: unknown): DictationIntentPayload | null {
  if (!isPlainObject(value)) return null;
  const { intent_type, fields, confidence } = value;
  if (typeof intent_type !== "string" || !INTENT_TYPES.has(intent_type)) return null;
  if (!isPlainObject(fields)) return null;
  if (
    typeof confidence !== "number" ||
    !Number.isFinite(confidence) ||
    confidence < 0 ||
    confidence > 1
  ) {
    return null;
  }
  return { intent_type: intent_type as DictationIntentType, fields, confidence };
}

export function parseDictationFinalPayload(
  payload: Record<string, unknown>,
): DictationFinalPayload | null {
  const { mode, text } = payload;
  if (mode !== "note" && mode !== "command" && mode !== "inject") return null;
  if (typeof text !== "string") return null;
  const result: {
    mode: DictationMode;
    text: string;
    note_path?: string;
    note_title?: string;
    title_source?: string;
    intent?: DictationIntentPayload;
    degraded_reason?: string;
    cleaned_text?: string;
    cleanup_source?: string;
    cleanup_latency_ms?: number;
    flush_ms?: number;
  } = { mode, text };
  // Optional fields: absent is fine; PRESENT-but-malformed fails the frame
  // (a half-valid final could send the user to a note that does not exist,
  // or paste the wrong artifact into their focused app).
  for (const key of [
    "note_path",
    "note_title",
    "title_source",
    "degraded_reason",
    "cleaned_text",
    "cleanup_source",
  ] as const) {
    const value = payload[key];
    if (value === undefined) continue;
    if (typeof value !== "string" || value.length === 0) return null;
    result[key] = value;
  }
  for (const key of ["cleanup_latency_ms", "flush_ms"] as const) {
    const value = payload[key];
    if (value === undefined) continue;
    // Latency stamps are shown to the user (speed showcase) — a bogus
    // number would be a lie on the surface, so the frame fails instead.
    if (typeof value !== "number" || !Number.isFinite(value) || value < 0) return null;
    result[key] = value;
  }
  if (payload["intent"] !== undefined) {
    const intent = parseIntent(payload["intent"]);
    if (intent === null) return null;
    result.intent = intent;
  }
  return result;
}

export function parseDictationErrorPayload(
  payload: Record<string, unknown>,
): DictationErrorPayload | null {
  const { reason } = payload;
  if (typeof reason !== "string" || reason.length === 0) return null;
  return { reason };
}
