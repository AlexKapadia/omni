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

/** Turn a source id like `zoom` / `google_meet` into a human meeting title. */
export function humanMeetingTitleFromSource(source: string): string {
  const trimmed = source.trim();
  if (!trimmed) return "Meeting";
  const label = trimmed
    .split(/[_\-\s]+/)
    .filter((part) => part.length > 0)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1).toLowerCase())
    .join(" ");
  return `${label} meeting`;
}

/** Optional Live navigation — App wires this the same way as tray start. */
export type NavigateLive = () => void;

let navigateLiveHandler: NavigateLive | undefined;

/** Register (or clear) the Live-nav callback used by the default auto-start path. */
export function setAutoStartNavigateLive(handler: NavigateLive | undefined): void {
  navigateLiveHandler = handler;
}

/**
 * If the suggestion is an engine-authorised auto-start and capture is idle,
 * navigate to Live (when wired) then send capture.start. No-op when already
 * live or the engine is unreachable.
 */
export function maybeAutoStartCaptureOnDetection(
  suggestion: MeetingSuggestion,
  store: TranscriptStore = transcriptStore,
  start: CaptureStarter = requestCaptureStart,
  onNavigateLive: NavigateLive | undefined = navigateLiveHandler,
): void {
  if (!suggestion.autoStart) return;
  const { captureStatus } = store.getState();
  if (captureStatus !== "idle" && captureStatus !== "stopped") return;
  // Same order as tray: navigate to Live, then start capture.
  onNavigateLive?.();
  start(humanMeetingTitleFromSource(suggestion.source));
}
