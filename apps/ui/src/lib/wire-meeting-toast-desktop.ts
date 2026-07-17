/**
 * Desktop meeting toast bridge (main window): show/hide the always-on-top
 * overlay from detection store state, and handle Start / Not now / Stop /
 * Keep going events emitted by the overlay shell commands.
 *
 * Single source of truth: the main window owns the engine socket and pushes
 * toast content through the show command so the overlay never needs its own WS.
 */
import { invoke } from "@tauri-apps/api/core";
import { requestCaptureStart, requestCaptureStop } from "./capture-commands";
import {
  clearStopHint,
  dismissMeetingSuggestion,
  meetingDetectionStore,
  type MeetingDetectionStore,
  type MeetingSuggestion,
} from "./meeting-detection-store";
import { transcriptStore, type TranscriptStore } from "./transcript-store";

export const MEETING_TOAST_START_EVENT = "meeting-toast-start-capture";
export const MEETING_TOAST_DISMISS_EVENT = "meeting-toast-dismiss";
export const MEETING_TOAST_STOP_EVENT = "meeting-toast-stop-capture";
export const MEETING_TOAST_KEEP_GOING_EVENT = "meeting-toast-keep-going";
/** Event the shell emits to the toast window with the payload to render. */
export const MEETING_TOAST_CONTENT_EVENT = "meeting-toast-content";

export type NavigateLive = () => void;

/** Payload pushed to the toast window (mirrors MeetingDetectionState). */
export interface MeetingToastContent {
  readonly suggestion: MeetingSuggestion | null;
  readonly stopHintReason: string | null;
}

async function applyVisibility(
  visible: boolean,
  content: MeetingToastContent | null,
): Promise<void> {
  try {
    // Always invoke (idempotent) — no lastVisible cache; Rust may have hidden
    // the window via Start / Dismiss / Keep going / Stop without our knowledge.
    await invoke("set_meeting_toast_visible", { visible, content });
  } catch {
    // Web build / tests: no Tauri shell — desktop toast unavailable.
  }
}

function shouldShowDesktopToast(
  detection: MeetingDetectionStore,
  transcript: TranscriptStore,
): boolean {
  const { suggestion, stopHintReason } = detection.getState();
  const { captureStatus } = transcript.getState();
  const canStart = captureStatus === "idle" || captureStatus === "stopped";
  if (suggestion !== null && !suggestion.autoStart && canStart) return true;
  if (stopHintReason !== null && captureStatus === "live") return true;
  return false;
}

function buildToastContent(detection: MeetingDetectionStore): MeetingToastContent {
  const { suggestion, stopHintReason } = detection.getState();
  return { suggestion, stopHintReason };
}

/**
 * Subscribe detection + capture state to the desktop toast window.
 * Returns an unsubscribe that also hides the overlay.
 */
export function wireMeetingToastDesktop(
  onNavigateLive: NavigateLive,
  detection: MeetingDetectionStore = meetingDetectionStore,
  transcript: TranscriptStore = transcriptStore,
  listen: (
    event: string,
    handler: (event: { payload: unknown }) => void,
  ) => Promise<() => void> = async () => () => {},
): () => void {
  const sync = (): void => {
    const visible = shouldShowDesktopToast(detection, transcript);
    const content = visible ? buildToastContent(detection) : null;
    void applyVisibility(visible, content);
  };

  const unsubDetection = detection.subscribe(sync);
  const unsubTranscript = transcript.subscribe(sync);
  sync();

  const unlisteners: Array<() => void> = [];
  void (async () => {
    try {
      unlisteners.push(
        await listen(MEETING_TOAST_START_EVENT, (event) => {
          const title =
            typeof event.payload === "string" && event.payload.trim().length > 0
              ? event.payload.trim()
              : undefined;
          onNavigateLive();
          requestCaptureStart(title);
        }),
      );
      unlisteners.push(
        await listen(MEETING_TOAST_DISMISS_EVENT, () => {
          dismissMeetingSuggestion(detection);
          clearStopHint(detection);
        }),
      );
      unlisteners.push(
        await listen(MEETING_TOAST_STOP_EVENT, () => {
          clearStopHint(detection);
          requestCaptureStop();
        }),
      );
      unlisteners.push(
        await listen(MEETING_TOAST_KEEP_GOING_EVENT, () => {
          // Overlay "Keep going" — clear the main-window stop hint so a later
          // capture.suggest_stop can show the toast again in this capture.
          clearStopHint(detection);
        }),
      );
    } catch {
      // Non-Tauri environments: event listen unavailable.
    }
  })();

  return () => {
    unsubDetection();
    unsubTranscript();
    for (const unlisten of unlisteners) unlisten();
    void applyVisibility(false, null);
  };
}
