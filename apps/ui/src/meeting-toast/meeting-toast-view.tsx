/**
 * Desktop meeting toast UI — rendered in the always-on-top overlay window.
 * Start / Not now / Stop go through Tauri shell commands so the main app acts.
 */
import { invoke } from "@tauri-apps/api/core";
import { Mic } from "lucide-react";
import { useStore } from "zustand";
import { humanMeetingTitleFromSource } from "../lib/auto-start-reaction";
import { meetingSourceToastLabel } from "../lib/detection-source-options";
import {
  clearStopHint,
  type MeetingDetectionStore,
} from "../lib/meeting-detection-store";
import { meetingToastDetectionStore } from "./meeting-toast-engine-bridge";

export function MeetingToastView({
  store = meetingToastDetectionStore,
}: {
  readonly store?: MeetingDetectionStore;
}) {
  const suggestion = useStore(store, (s) => s.suggestion);
  const stopHintReason = useStore(store, (s) => s.stopHintReason);

  const showSuggest = suggestion !== null && !suggestion.autoStart;
  const showStop = stopHintReason !== null && !showSuggest;

  if (!showSuggest && !showStop) {
    return <div className="meeting-toast-shell" aria-hidden />;
  }

  if (showSuggest && suggestion !== null) {
    const sourceLabel = meetingSourceToastLabel(suggestion.source);
    const title = humanMeetingTitleFromSource(suggestion.source);
    return (
      <div className="meeting-toast-shell">
        <div className="meeting-toast-card" role="status" aria-label="Meeting detected">
          <div className="meeting-toast-row">
            <span className="meeting-toast-icon" aria-hidden>
              <Mic size={18} strokeWidth={2} />
            </span>
            <div className="meeting-toast-copy">
              <p className="meeting-toast-title">{sourceLabel} meeting detected</p>
              <p className="meeting-toast-body">
                Capture on this device — nothing joins the call.
              </p>
            </div>
          </div>
          <div className="meeting-toast-actions">
            <button
              type="button"
              className="meeting-toast-primary"
              onClick={() => {
                void invoke("meeting_toast_start_capture", { title });
              }}
            >
              Start capture
            </button>
            <button
              type="button"
              className="meeting-toast-ghost"
              onClick={() => {
                void invoke("meeting_toast_dismiss");
              }}
            >
              Not now
            </button>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="meeting-toast-shell">
      <div className="meeting-toast-card" role="status" aria-label="Capture stop suggested">
        <div className="meeting-toast-copy">
          <p className="meeting-toast-title">Meeting looks over</p>
          <p className="meeting-toast-body">{stopHintReason} — stop capturing?</p>
        </div>
        <div className="meeting-toast-actions">
          <button
            type="button"
            className="meeting-toast-primary"
            onClick={() => {
              clearStopHint(store);
              void invoke("meeting_toast_stop_capture");
            }}
          >
            Stop capture
          </button>
          <button
            type="button"
            className="meeting-toast-ghost"
            onClick={() => {
              clearStopHint(store);
              void invoke("set_meeting_toast_visible", { visible: false });
            }}
          >
            Keep going
          </button>
        </div>
      </div>
    </div>
  );
}
