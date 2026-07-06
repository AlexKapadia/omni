/**
 * Detection surface on the live screen: the bot-free "Start capturing?"
 * suggestion toast (meeting.detected) and the "meeting looks over" stop
 * hint (capture.suggest_stop) while capture runs.
 *
 * Approval-before-execute: the toast only ever OFFERS — starting sends the
 * ordinary capture.start command; dismissing sends detection.dismiss so the
 * engine's cooldown honours the "no". Nothing acts on the user's behalf.
 */
import { useStore } from "zustand";
import { OmniButton } from "../button";
import { requestCaptureStart, requestCaptureStop } from "../../lib/capture-commands";
import {
  clearStopHint,
  dismissMeetingSuggestion,
  meetingDetectionStore,
  type MeetingDetectionStore,
} from "../../lib/meeting-detection-store";
import { useTranscript } from "../../lib/transcript-store";

const TOAST_CLASS =
  "pointer-events-auto flex flex-col items-start border border-[var(--grey-200)] bg-[var(--paper,#fff)]";

export function MeetingDetectedToast({
  store = meetingDetectionStore,
}: {
  readonly store?: MeetingDetectionStore;
}) {
  const suggestion = useStore(store, (s) => s.suggestion);
  const stopHintReason = useStore(store, (s) => s.stopHintReason);
  const captureStatus = useTranscript((s) => s.captureStatus);
  const canStart = captureStatus === "idle" || captureStatus === "stopped";
  const isLive = captureStatus === "live";

  if (suggestion === null && !(stopHintReason !== null && isLive)) return null;

  return (
    <div
      className="pointer-events-none absolute left-0 right-0 top-0 z-20 flex justify-center"
      style={{ padding: "var(--space-4)" }}
    >
      {suggestion !== null && canStart ? (
        <div
          role="status"
          aria-label="Meeting detected"
          className={TOAST_CLASS}
          style={{
            borderRadius: "var(--radius-card, 8px)",
            boxShadow: "var(--shadow-card, 0 4px 16px rgba(0,0,0,0.08))",
            padding: "var(--space-4) var(--space-6)",
            gap: "var(--space-3)",
          }}
        >
          <p className="m-0 text-[var(--ink)]" style={{ fontSize: 13 }}>
            {suggestion.reason} — start capturing?
          </p>
          <div className="flex items-center gap-[var(--space-3)]">
            <OmniButton
              variant="primary"
              small
              onClick={() => {
                // One click, ordinary command path: capture.started will
                // clear this card through the event wiring.
                requestCaptureStart();
              }}
            >
              Start capture
            </OmniButton>
            <OmniButton variant="ghost" small onClick={() => dismissMeetingSuggestion(store)}>
              Dismiss
            </OmniButton>
          </div>
        </div>
      ) : stopHintReason !== null && isLive ? (
        <div
          role="status"
          aria-label="Capture stop suggested"
          className={TOAST_CLASS}
          style={{
            borderRadius: "var(--radius-card, 8px)",
            boxShadow: "var(--shadow-card, 0 4px 16px rgba(0,0,0,0.08))",
            padding: "var(--space-4) var(--space-6)",
            gap: "var(--space-3)",
          }}
        >
          <p className="m-0 text-[var(--ink)]" style={{ fontSize: 13 }}>
            {stopHintReason} — stop capturing?
          </p>
          <div className="flex items-center gap-[var(--space-3)]">
            <OmniButton
              variant="secondary"
              small
              onClick={() => {
                clearStopHint(store);
                requestCaptureStop();
              }}
            >
              Stop capture
            </OmniButton>
            <OmniButton variant="ghost" small onClick={() => clearStopHint(store)}>
              Keep going
            </OmniButton>
          </div>
        </div>
      ) : null}
    </div>
  );
}
