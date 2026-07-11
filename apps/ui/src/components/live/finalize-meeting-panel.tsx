/**
 * Post-capture finalize panel: shown on the live screen once capture stops,
 * offering "Finalize meeting" — meeting.finalize with the notepad buffer
 * carried VERBATIM (fidelity mandate) — with honest pending/ready/failed
 * states driven by the reply and the engine's enhance.* progress events.
 *
 * No state is faked: pending only after the command was sent, ready shows
 * the real vault note path, failed shows the engine's own reason + a retry.
 */
import { useStore } from "zustand";
import { OmniButton } from "../button";
import {
  finalizeMeeting,
  meetingFinalizeStore,
  type MeetingFinalizeStore,
} from "../../lib/meeting-finalize-store";
import { notepadStore, type NotepadStore } from "../../lib/notepad-store";
import { appSettingsStore, type SettingsStore } from "../../lib/settings-store";

export function FinalizeMeetingPanel({
  meetingId,
  store = meetingFinalizeStore,
  notepad = notepadStore,
  settingsStore = appSettingsStore,
}: {
  readonly meetingId: string;
  readonly store?: MeetingFinalizeStore;
  readonly notepad?: NotepadStore;
  readonly settingsStore?: SettingsStore;
}) {
  const status = useStore(store, (s) => s.status);
  const notePath = useStore(store, (s) => s.notePath);
  const errorMessage = useStore(store, (s) => s.errorMessage);
  const warnings = useStore(store, (s) => s.warnings);
  const autoSummary = useStore(settingsStore, (s) => s.settings?.autoSummary ?? false);

  const startFinalize = () => {
    // The notepad buffer travels verbatim — the engine stores exact bytes.
    const activeTemplate = settingsStore.getState().settings?.activeTemplate ?? null;
    void finalizeMeeting(meetingId, notepad.getState().text, store, undefined, activeTemplate);
  };

  if (status === "ready" && notePath !== null) {
    return (
      <div className="flex flex-col items-start gap-[var(--space-2)]">
        <p className="m-0 text-[var(--ink)]" style={{ fontSize: 13 }}>
          Enhanced note saved to{" "}
          <span className="font-[family-name:var(--font-mono)]">{notePath}</span>
        </p>
        {warnings.length > 0 && (
          <p className="m-0 text-[var(--grey-600)]" style={{ fontSize: 12 }}>
            {/* Honest partial success: the note exists; these steps degraded. */}
            {warnings.join("; ")}
          </p>
        )}
      </div>
    );
  }

  return (
    <div className="flex flex-col items-start gap-[var(--space-2)]">
      {autoSummary && status === "idle" && (
        <p className="m-0 text-[var(--grey-600)]" style={{ fontSize: 12 }}>
          Auto-summary is on — this runs automatically now that capture has stopped.
        </p>
      )}
      <OmniButton variant="primary" disabled={status === "pending"} onClick={startFinalize}>
        {status === "pending"
          ? "Enhancing notes"
          : status === "failed"
            ? "Retry finalize"
            : "Finalize meeting"}
      </OmniButton>
      {status === "pending" && (
        <p className="m-0 text-[var(--grey-600)]" style={{ fontSize: 12 }}>
          Fusing your notes with the transcript on this device's meeting record…
        </p>
      )}
      {status === "failed" && errorMessage !== null && (
        <p role="alert" className="m-0 text-[var(--grey-600)]" style={{ fontSize: 12 }}>
          {errorMessage}
        </p>
      )}
    </div>
  );
}
