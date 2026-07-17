/**
 * Desktop meeting toast bridge (main window): show/hide the always-on-top
 * overlay from detection store state, and handle Start / Not now / Stop
 * events emitted by the overlay shell commands.
 */
import { invoke } from "@tauri-apps/api/core";
import { requestCaptureStart, requestCaptureStop } from "./capture-commands";
import {
  clearStopHint,
  dismissMeetingSuggestion,
  meetingDetectionStore,
  type MeetingDetectionStore,
} from "./meeting-detection-store";
import { transcriptStore, type TranscriptStore } from "./transcript-store";

export const MEETING_TOAST_START_EVENT = "meeting-toast-start-capture";
export const MEETING_TOAST_DISMISS_EVENT = "meeting-toast-dismiss";
export const MEETING_TOAST_STOP_EVENT = "meeting-toast-stop-capture";

export type NavigateLive = () => void;

async function applyVisibility(visible: boolean): Promise<void> {
  try {
    await invoke("set_meeting_toast_visible", { visible });
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
  let lastVisible: boolean | null = null;

  const sync = (): void => {
    const visible = shouldShowDesktopToast(detection, transcript);
    if (visible === lastVisible) return;
    const wasVisible = lastVisible === true;
    lastVisible = visible;
    if (visible || wasVisible) {
      void applyVisibility(visible);
    }
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
    } catch {
      // Non-Tauri environments: event listen unavailable.
    }
  })();

  return () => {
    unsubDetection();
    unsubTranscript();
    for (const unlisten of unlisteners) unlisten();
    if (lastVisible === true) {
      void applyVisibility(false);
    }
  };
}
