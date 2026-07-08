/**
 * Auto-start reaction: when the engine emits `meeting.detected` with
 * `auto_start: true` (user opted in per-source on the engine side), the UI
 * fires the ordinary `capture.start` command without waiting for a toast click.
 *
 * Approval-before-execute is preserved: auto-start only happens when the
 * engine has already gated on `auto_start_sources` + confidence thresholds.
 */
import { requestCaptureStart } from "./capture-commands";
import type { MeetingSuggestion } from "./meeting-detection-store";
import { transcriptStore, type TranscriptStore } from "./transcript-store";

export type CaptureStarter = (title?: string) => boolean;

/**
 * If the suggestion is an engine-authorised auto-start and capture is idle,
 * send capture.start. No-op when already live or the engine is unreachable.
 */
export function maybeAutoStartCaptureOnDetection(
  suggestion: MeetingSuggestion,
  store: TranscriptStore = transcriptStore,
  start: CaptureStarter = requestCaptureStart,
): void {
  if (!suggestion.autoStart) return;
  const { captureStatus } = store.getState();
  if (captureStatus !== "idle" && captureStatus !== "stopped") return;
  start(suggestion.source);
}
