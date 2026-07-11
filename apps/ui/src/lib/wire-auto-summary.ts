/**
 * Auto-summary on stop (Meetily-style): when `autoSummary` is on, finalizing
 * the meeting note happens automatically the moment capture stops — no
 * click required. Subscribes once at app start, mirroring wire-captions-overlay.ts's
 * pattern (a raw engine-frame subscription rather than the transcript store,
 * so it does not race the transcript store's own capture.stopped handling).
 */
import { subscribeToEngineFrames } from "./live-engine-socket";
import { parseInboundMessage } from "./protocol";
import { CAPTURE_STOPPED_EVENT_NAME, parseCaptureStoppedPayload } from "./capture-protocol";
import { finalizeMeeting, meetingFinalizeStore, type MeetingFinalizeStore } from "./meeting-finalize-store";
import { notepadStore, type NotepadStore } from "./notepad-store";
import { appSettingsStore, type SettingsStore } from "./settings-store";

export type SubscribeFramesFn = (listener: (data: unknown) => void) => () => void;
export type FinalizeFn = typeof finalizeMeeting;

/**
 * Subscribe once; returns an unsubscribe. On every `capture.stopped` event,
 * finalizes the meeting IF the user opted into auto-summary and no finalize
 * flow is already pending (finalizeMeeting itself is the single source of
 * truth for "already pending" — this never duplicates its guard).
 */
export function wireAutoSummary(
  settingsStore: SettingsStore = appSettingsStore,
  finalizeStore: MeetingFinalizeStore = meetingFinalizeStore,
  notepad: NotepadStore = notepadStore,
  subscribeFrames: SubscribeFramesFn = subscribeToEngineFrames,
  finalize: FinalizeFn = finalizeMeeting,
): () => void {
  return subscribeFrames((data) => {
    const parsed = parseInboundMessage(data);
    if (!parsed.ok || parsed.envelope.kind !== "event") return;
    if (parsed.envelope.name !== CAPTURE_STOPPED_EVENT_NAME) return;
    const stopped = parseCaptureStoppedPayload(parsed.envelope.payload);
    if (stopped === null) return;
    const autoSummary = settingsStore.getState().settings?.autoSummary ?? false;
    if (!autoSummary) return;
    if (finalizeStore.getState().status === "pending") return;
    const activeTemplate = settingsStore.getState().settings?.activeTemplate ?? null;
    void finalize(
      stopped.meeting_id,
      notepad.getState().text,
      finalizeStore,
      undefined,
      activeTemplate,
    );
  });
}
