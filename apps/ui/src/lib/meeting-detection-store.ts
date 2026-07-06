/**
 * Zustand store for M6 bot-free detection: the "Start capturing?" suggestion
 * card and the "meeting looks over" stop hint, fed by the engine's
 * `meeting.detected` / `capture.suggest_stop` events.
 *
 * Security / honesty invariants:
 * - Fail-closed parse: a malformed payload is dropped whole — it never
 *   mutates the store (untrusted inbound frame rule).
 * - Detection only ever SUGGESTS: accepting a card sends the ordinary
 *   capture.start command; dismissing sends `detection.dismiss` so the
 *   engine's cooldown honours the "no" (approval-before-execute).
 */
import { createStore, useStore, type StoreApi } from "zustand";
import { sendEngineCommand } from "./live-engine-socket";

/** Event/command names pinned with the engine (detection_event_payloads.py). */
export const MEETING_DETECTED_EVENT_NAME = "meeting.detected";
export const CAPTURE_SUGGEST_STOP_EVENT_NAME = "capture.suggest_stop";
export const DETECTION_DISMISS_COMMAND_NAME = "detection.dismiss";

export interface MeetingSuggestion {
  readonly source: string;
  readonly reason: string;
  readonly confidence: number;
  /** Present for suggestion cards; echoed back on dismiss. */
  readonly dedupeKey: string | null;
  /** True only for the user-opted-in auto-start path (engine-enforced). */
  readonly autoStart: boolean;
}

export interface MeetingDetectionState {
  /** The current suggestion card, or null (the honest idle state). */
  readonly suggestion: MeetingSuggestion | null;
  /** The "meeting looks over" hint while capture still runs, or null. */
  readonly stopHintReason: string | null;
}

export const INITIAL_MEETING_DETECTION_STATE: MeetingDetectionState = {
  suggestion: null,
  stopHintReason: null,
};

export type MeetingDetectionStore = StoreApi<MeetingDetectionState>;

export function createMeetingDetectionStore(): MeetingDetectionStore {
  return createStore<MeetingDetectionState>(() => INITIAL_MEETING_DETECTION_STATE);
}

/** The one store the running app uses. Tests create their own. */
export const meetingDetectionStore: MeetingDetectionStore = createMeetingDetectionStore();

export function useMeetingDetection<T>(selector: (state: MeetingDetectionState) => T): T {
  return useStore(meetingDetectionStore, selector);
}

function isPlainObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

/**
 * Validate one `meeting.detected` payload against the pinned engine
 * contract. Returns null on ANY deviation (fail closed).
 */
export function parseMeetingDetectedPayload(payload: unknown): MeetingSuggestion | null {
  if (!isPlainObject(payload)) return null;
  const { source, reason, confidence, dedupe_key, auto_start } = payload;
  if (typeof source !== "string" || source.length === 0) return null;
  if (typeof reason !== "string" || reason.length === 0) return null;
  if (typeof confidence !== "number" || !Number.isFinite(confidence)) return null;
  if (confidence < 0 || confidence > 1) return null; // engine validates; mirror it
  if (dedupe_key !== undefined && (typeof dedupe_key !== "string" || dedupe_key.length === 0)) {
    return null;
  }
  if (auto_start !== undefined && auto_start !== true) return null; // present ⇒ literal true
  return {
    source,
    reason,
    confidence,
    dedupeKey: typeof dedupe_key === "string" ? dedupe_key : null,
    autoStart: auto_start === true,
  };
}

/** Apply one raw `meeting.detected` payload: parse fail-closed, then show. */
export function applyMeetingDetected(store: MeetingDetectionStore, payload: unknown): void {
  const suggestion = parseMeetingDetectedPayload(payload);
  if (suggestion === null) return; // fail closed: malformed frames change nothing
  store.setState({ suggestion });
}

/** Apply one raw `capture.suggest_stop` payload (fail-closed). */
export function applyCaptureSuggestStop(store: MeetingDetectionStore, payload: unknown): void {
  if (!isPlainObject(payload)) return;
  const reason = payload["reason"];
  if (typeof reason !== "string" || reason.length === 0) return;
  store.setState({ stopHintReason: reason });
}

/** Capture started (by any path): the suggestion is consumed, hints reset. */
export function clearMeetingDetection(
  store: MeetingDetectionStore = meetingDetectionStore,
): void {
  store.setState(INITIAL_MEETING_DETECTION_STATE, true);
}

/** The user closed the stop hint without stopping — hide it, change nothing. */
export function clearStopHint(store: MeetingDetectionStore = meetingDetectionStore): void {
  store.setState({ stopHintReason: null });
}

export type CommandSender = (name: string, payload?: Record<string, unknown>) => boolean;

/**
 * The user said "no": clear the card and tell the engine so its cooldown
 * suppresses the same source (deny re-suggesting for the cooldown window).
 * Cards without a dedupe key (auto-start notices) just clear locally.
 */
export function dismissMeetingSuggestion(
  store: MeetingDetectionStore = meetingDetectionStore,
  send: CommandSender = sendEngineCommand,
): void {
  const suggestion = store.getState().suggestion;
  if (suggestion === null) return;
  if (suggestion.dedupeKey !== null) {
    // Best-effort: an offline engine cannot record the cooldown, but the
    // card still clears — the user's "no" is honoured locally regardless.
    send(DETECTION_DISMISS_COMMAND_NAME, { dedupe_key: suggestion.dedupeKey });
  }
  store.setState({ suggestion: null });
}
