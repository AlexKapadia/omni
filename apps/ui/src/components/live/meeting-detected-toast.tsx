/**
 * Global detection surface: calm Daylight toast for meeting.detected and
 * capture.suggest_stop. Mounted on the app shell so Home / Library / Settings
 * see detections — not only the Live screen.
 *
 * Approval-before-execute: offers only; Start runs the ordinary capture path
 * (caller may navigate to Live first); Dismiss sends detection.dismiss.
 */
import { AnimatePresence, motion, useReducedMotion } from "framer-motion";
import { Mic } from "lucide-react";
import { useStore } from "zustand";
import { OmniButton } from "../button";
import { requestCaptureStart, requestCaptureStop } from "../../lib/capture-commands";
import { meetingSourceToastLabel } from "../../lib/detection-source-options";
import {
  clearStopHint,
  dismissMeetingSuggestion,
  meetingDetectionStore,
  type MeetingDetectionStore,
} from "../../lib/meeting-detection-store";
import { useTranscript } from "../../lib/transcript-store";

export function MeetingDetectedToast({
  store = meetingDetectionStore,
  onStartCapture,
}: {
  readonly store?: MeetingDetectionStore;
  /** When set (app shell), navigate + start; otherwise send capture.start alone. */
  readonly onStartCapture?: () => void;
}) {
  const suggestion = useStore(store, (s) => s.suggestion);
  const stopHintReason = useStore(store, (s) => s.stopHintReason);
  const captureStatus = useTranscript((s) => s.captureStatus);
  const canStart = captureStatus === "idle" || captureStatus === "stopped";
  const isLive = captureStatus === "live";
  const reducedMotion = useReducedMotion();

  const showSuggest = suggestion !== null && canStart && !suggestion.autoStart;
  const showStop = stopHintReason !== null && isLive;
  if (!showSuggest && !showStop) return null;

  const sourceLabel =
    suggestion !== null ? meetingSourceToastLabel(suggestion.source) : "Meeting";

  return (
    <div
      className="pointer-events-none fixed bottom-20 right-4 z-50 flex max-w-[min(380px,calc(100vw-2rem))] justify-end"
      style={{ padding: "var(--space-2)" }}
    >
      <AnimatePresence mode="wait">
        {showSuggest ? (
          <motion.div
            key="suggest"
            role="status"
            aria-label="Meeting detected"
            className="pointer-events-auto flex w-full flex-col border border-[var(--grey-200)] bg-[var(--surface)]"
            initial={reducedMotion ? false : { opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            exit={reducedMotion ? undefined : { opacity: 0, y: 6 }}
            transition={{ duration: 0.2, ease: [0.16, 1, 0.3, 1] }}
            style={{
              borderRadius: "var(--radius-card)",
              boxShadow: "var(--shadow-float)",
              padding: "var(--space-5)",
              gap: "var(--space-4)",
            }}
          >
            <div className="flex items-start gap-[var(--space-3)]">
              <span
                className="mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-[var(--radius-control)] bg-[var(--accent-subtle)] text-[var(--accent)]"
                aria-hidden
              >
                <Mic size={18} strokeWidth={2} />
              </span>
              <div className="min-w-0 flex-1">
                <p
                  className="m-0 font-[family-name:var(--font-display)] font-semibold text-[var(--ink)]"
                  style={{ fontSize: 17, letterSpacing: "-0.02em", textWrap: "balance" }}
                >
                  {sourceLabel} meeting detected
                </p>
                <p
                  className="m-0 mt-[var(--space-1)] text-[var(--ink-secondary)]"
                  style={{ fontSize: 13, lineHeight: 1.45 }}
                >
                  Capture on this device — nothing joins the call.
                </p>
              </div>
            </div>
            <div className="flex items-center gap-[var(--space-3)]">
              <OmniButton
                variant="primary"
                small
                onClick={() => {
                  if (onStartCapture !== undefined) onStartCapture();
                  else requestCaptureStart();
                }}
              >
                Start capture
              </OmniButton>
              <OmniButton variant="ghost-dismiss" small onClick={() => dismissMeetingSuggestion(store)}>
                Not now
              </OmniButton>
            </div>
          </motion.div>
        ) : showStop ? (
          <motion.div
            key="stop"
            role="status"
            aria-label="Capture stop suggested"
            className="pointer-events-auto flex w-full flex-col border border-[var(--grey-200)] bg-[var(--surface)]"
            initial={reducedMotion ? false : { opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            exit={reducedMotion ? undefined : { opacity: 0, y: 6 }}
            transition={{ duration: 0.2, ease: [0.16, 1, 0.3, 1] }}
            style={{
              borderRadius: "var(--radius-card)",
              boxShadow: "var(--shadow-float)",
              padding: "var(--space-5)",
              gap: "var(--space-4)",
            }}
          >
            <div>
              <p
                className="m-0 font-[family-name:var(--font-display)] font-semibold text-[var(--ink)]"
                style={{ fontSize: 17, letterSpacing: "-0.02em" }}
              >
                Meeting looks over
              </p>
              <p
                className="m-0 mt-[var(--space-1)] text-[var(--ink-secondary)]"
                style={{ fontSize: 13, lineHeight: 1.45 }}
              >
                {stopHintReason} — stop capturing?
              </p>
            </div>
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
              <OmniButton variant="ghost-dismiss" small onClick={() => clearStopHint(store)}>
                Keep going
              </OmniButton>
            </div>
          </motion.div>
        ) : null}
      </AnimatePresence>
    </div>
  );
}
