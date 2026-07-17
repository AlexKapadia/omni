/**
 * Overlay-local detection store for the desktop meeting toast.
 * Content arrives from the main window via the shell (Tauri event), never
 * from a second engine WebSocket — main is the single source of truth.
 */
import {
  createMeetingDetectionStore,
  type MeetingDetectionStore,
  type MeetingSuggestion,
  INITIAL_MEETING_DETECTION_STATE,
} from "../lib/meeting-detection-store";
import type { MeetingToastContent } from "../lib/wire-meeting-toast-desktop";

/** Overlay-local store (not shared with the main window JS heap). */
export const meetingToastContentStore: MeetingDetectionStore = createMeetingDetectionStore();

function isPlainObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function parseSuggestion(value: unknown): MeetingSuggestion | null {
  if (value === null) return null;
  if (!isPlainObject(value)) return null;
  const { source, reason, confidence, dedupeKey, autoStart } = value;
  if (typeof source !== "string" || source.length === 0) return null;
  if (typeof reason !== "string" || reason.length === 0) return null;
  if (typeof confidence !== "number" || !Number.isFinite(confidence)) return null;
  if (confidence < 0 || confidence > 1) return null;
  if (dedupeKey !== null && dedupeKey !== undefined && typeof dedupeKey !== "string") {
    return null;
  }
  if (autoStart !== undefined && typeof autoStart !== "boolean") return null;
  return {
    source,
    reason,
    confidence,
    dedupeKey: typeof dedupeKey === "string" ? dedupeKey : null,
    autoStart: autoStart === true,
  };
}

/**
 * Apply a content payload from the main window. Fail-closed: malformed frames
 * clear to idle so we never render a stale Start card as a stop hint.
 */
export function applyMeetingToastContent(
  store: MeetingDetectionStore,
  payload: unknown,
): void {
  if (payload === null || payload === undefined) {
    store.setState(INITIAL_MEETING_DETECTION_STATE, true);
    return;
  }
  if (!isPlainObject(payload)) {
    store.setState(INITIAL_MEETING_DETECTION_STATE, true);
    return;
  }
  const suggestion = parseSuggestion(payload["suggestion"] ?? null);
  const stopRaw = payload["stopHintReason"];
  const stopHintReason =
    stopRaw === null || stopRaw === undefined
      ? null
      : typeof stopRaw === "string" && stopRaw.length > 0
        ? stopRaw
        : null;
  // Reject frames where both are invalid / empty (nothing to show).
  if (suggestion === null && stopHintReason === null) {
    // Still accept an explicit empty content (both null) as clear.
    if (payload["suggestion"] === null && payload["stopHintReason"] === null) {
      store.setState(INITIAL_MEETING_DETECTION_STATE, true);
    }
    return;
  }
  store.setState({ suggestion, stopHintReason });
}

/** Type guard helper for tests and listeners. */
export function asMeetingToastContent(payload: unknown): MeetingToastContent | null {
  if (!isPlainObject(payload)) return null;
  const suggestion = parseSuggestion(payload["suggestion"] ?? null);
  const stopRaw = payload["stopHintReason"];
  const stopHintReason =
    stopRaw === null || stopRaw === undefined
      ? null
      : typeof stopRaw === "string" && stopRaw.length > 0
        ? stopRaw
        : null;
  if (suggestion === null && stopHintReason === null) {
    if (payload["suggestion"] === null && payload["stopHintReason"] === null) {
      return { suggestion: null, stopHintReason: null };
    }
    return null;
  }
  return { suggestion, stopHintReason };
}
