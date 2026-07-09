/**
 * TypeScript mirror of the M1 capture/transcript additions to WS protocol v1.
 *
 * Mirrors engine/protocol/capture_event_payloads.py EXACTLY (field names are
 * pinned by the engine; changes there are breaking here). Additive companion
 * to protocol.ts — the envelope itself is parsed there; this file validates
 * the per-event payloads.
 *
 * Security invariant: every payload is untrusted input (prompt-injection and
 * malformed-frame defence). Every parser is fail-closed — any deviation from
 * the pinned shape returns null, never a partially-coerced object.
 */

// --- message names (pinned, dot-namespaced like "engine.heartbeat") ---
export const CAPTURE_START_COMMAND_NAME = "capture.start";
export const CAPTURE_STOP_COMMAND_NAME = "capture.stop";
export const CAPTURE_STARTED_EVENT_NAME = "capture.started";
export const CAPTURE_STOPPED_EVENT_NAME = "capture.stopped";
export const CAPTURE_DEVICE_CHANGED_EVENT_NAME = "capture.device_changed";
export const TRANSCRIPT_PARTIAL_EVENT_NAME = "transcript.partial";
export const TRANSCRIPT_FINAL_EVENT_NAME = "transcript.final";

/** Pinned by the DB CHECK constraint and StreamLabel enum: "me" = the user's
 *  microphone, "them" = WASAPI loopback of everyone else. */
export type StreamLabel = "me" | "them";

export interface TranscriptPartialPayload {
  readonly stream: StreamLabel;
  readonly text: string;
  readonly t_start: number;
  readonly t_end: number;
  readonly seq: number;
  readonly speaker_id?: string;
  readonly speaker_label?: string;
}

export interface TranscriptFinalPayload extends TranscriptPartialPayload {
  readonly segment_id: string; // matches the transcript_segments DB row
  readonly lag_ms: number; // audio-end -> emit latency (speed is a showcase)
}

export interface CaptureStartedPayload {
  readonly meeting_id: string;
  readonly reason: string;
}

export interface CaptureStoppedPayload {
  readonly meeting_id: string;
  readonly reason: string; // "command" or "error"
}

export interface CaptureDeviceChangedPayload {
  readonly device_name: string;
  readonly recovered_ms: number; // measured close-old -> open-new time
}

function isStreamLabel(value: unknown): value is StreamLabel {
  return value === "me" || value === "them";
}

/** Finite, non-negative number — NaN/Infinity/negative all fail closed. */
function isNonNegativeFinite(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value) && value >= 0;
}

function isNonNegativeInteger(value: unknown): value is number {
  return typeof value === "number" && Number.isInteger(value) && value >= 0;
}

function isNonEmptyString(value: unknown): value is string {
  return typeof value === "string" && value.length > 0;
}

/** Shared core of partial/final validation; null on ANY deviation. */
function parseTranscriptCore(payload: Record<string, unknown>): TranscriptPartialPayload | null {
  const { stream, text, t_start, t_end, seq } = payload;
  if (!isStreamLabel(stream)) return null;
  if (typeof text !== "string") return null;
  if (!isNonNegativeFinite(t_start) || !isNonNegativeFinite(t_end)) return null;
  if (t_end < t_start) return null; // a segment cannot end before it starts
  if (!isNonNegativeInteger(seq)) return null;
  const speaker_id = typeof payload["speaker_id"] === "string" ? payload["speaker_id"] : undefined;
  const speaker_label =
    typeof payload["speaker_label"] === "string" ? payload["speaker_label"] : undefined;
  return { stream, text, t_start, t_end, seq, speaker_id, speaker_label };
}

export function parseTranscriptPartialPayload(
  payload: Record<string, unknown>,
): TranscriptPartialPayload | null {
  return parseTranscriptCore(payload);
}

export function parseTranscriptFinalPayload(
  payload: Record<string, unknown>,
): TranscriptFinalPayload | null {
  const core = parseTranscriptCore(payload);
  if (core === null) return null;
  const { segment_id, lag_ms } = payload;
  if (!isNonEmptyString(segment_id)) return null;
  if (!isNonNegativeFinite(lag_ms)) return null;
  return { ...core, segment_id, lag_ms };
}

export function parseCaptureStartedPayload(
  payload: Record<string, unknown>,
): CaptureStartedPayload | null {
  const { meeting_id, reason } = payload;
  if (!isNonEmptyString(meeting_id) || !isNonEmptyString(reason)) return null;
  return { meeting_id, reason };
}

export function parseCaptureStoppedPayload(
  payload: Record<string, unknown>,
): CaptureStoppedPayload | null {
  const { meeting_id, reason } = payload;
  if (!isNonEmptyString(meeting_id) || !isNonEmptyString(reason)) return null;
  return { meeting_id, reason };
}

export function parseCaptureDeviceChangedPayload(
  payload: Record<string, unknown>,
): CaptureDeviceChangedPayload | null {
  const { device_name, recovered_ms } = payload;
  if (!isNonEmptyString(device_name)) return null;
  if (!isNonNegativeFinite(recovered_ms)) return null;
  return { device_name, recovered_ms };
}
