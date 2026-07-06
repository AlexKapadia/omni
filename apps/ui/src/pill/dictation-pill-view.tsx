/**
 * The dictation pill — design §07, every state real:
 * idle (flat wave · 00:00 grey · NOTE ghost · breathing dot + "Hold F9"),
 * listening (live wave · running timer · ink chip; chip inverts to COMMAND
 * + mono echo when the wake word is heard), processing, result popover
 * (note saved / intent recorded), and error — all driven by the store.
 */
import { useEffect, useState } from "react";
import { getCurrentWindow } from "@tauri-apps/api/window";

import type { DictationFinalPayload } from "./dictation-events-protocol";
import { RESULT_AUTO_DISMISS_MS, formatHoldTimer } from "./dictation-pill-state";
import { dictationPillStore, dispatchPillEvent, usePillState } from "./dictation-pill-store";
import { PillWaveformCanvas } from "./pill-waveform-canvas";

/** Build the obsidian:// URI for a saved Inbox note from its file path. */
export function obsidianOpenUriFromNotePath(notePath: string): string {
  const basename = notePath.split(/[\\/]/).pop() ?? notePath;
  const stem = basename.replace(/\.md$/, "");
  return `obsidian://open?file=${encodeURIComponent(`Inbox/${stem}`)}`;
}

function dismiss(): void {
  dispatchPillEvent(dictationPillStore, { type: "dismiss" });
}

function HoldTimer({ startedAtMs }: { readonly startedAtMs: number }) {
  const [nowMs, setNowMs] = useState(() => Date.now());
  useEffect(() => {
    const timer = setInterval(() => setNowMs(Date.now()), 250);
    return () => clearInterval(timer);
  }, []);
  return <span className="pill-timer">{formatHoldTimer(nowMs - startedAtMs)}</span>;
}

function ResultPopover({ final }: { readonly final: DictationFinalPayload }) {
  if (final.mode === "note") {
    return (
      <div className="pill-popover" role="status">
        <span className="pill-popover-label">
          {final.title_source === "fallback" ? "Note saved · offline title" : "Note saved"}
        </span>
        <span className="pill-popover-quote">“{final.text}”</span>
        <span className="pill-popover-title">{final.note_title ?? "Untitled"}</span>
        {final.degraded_reason !== undefined && (
          <span className="pill-popover-detail">{final.degraded_reason}</span>
        )}
        <div className="pill-popover-buttons">
          {final.note_path !== undefined && (
            <a
              className="pill-button-primary"
              href={obsidianOpenUriFromNotePath(final.note_path)}
            >
              Open in Obsidian
            </a>
          )}
          <button type="button" className="pill-button-ghost" onClick={dismiss}>
            Dismiss
          </button>
        </div>
      </div>
    );
  }
  const intent = final.intent;
  const label =
    intent !== undefined ? intent.intent_type.replace(/_/g, " ") : "command";
  const fieldsSummary =
    intent !== undefined
      ? Object.entries(intent.fields)
          .map(([key, value]) => `${key}: ${String(value)}`)
          .join(" · ")
      : "";
  return (
    <div className="pill-popover" role="status">
      <span className="pill-popover-label">{label}</span>
      <span className="pill-popover-quote">“{final.text}”</span>
      {fieldsSummary !== "" && <span className="pill-popover-detail">{fieldsSummary}</span>}
      {/* Approval-before-execute, stated honestly on the surface itself. */}
      <span className="pill-popover-detail">
        {intent !== undefined && intent.intent_type !== "unknown"
          ? "Recorded for approval — nothing runs until you approve it."
          : "Heard, but not understood — recorded only."}
      </span>
      <div className="pill-popover-buttons">
        <button type="button" className="pill-button-ghost" onClick={dismiss}>
          Dismiss
        </button>
      </div>
    </div>
  );
}

export function DictationPillView() {
  const state = usePillState((s) => s);

  // Result popovers self-dismiss; errors linger a little longer than results
  // so the reason is actually readable.
  useEffect(() => {
    if (state.phase !== "result" && state.phase !== "error") return;
    const timer = setTimeout(dismiss, RESULT_AUTO_DISMISS_MS);
    return () => clearTimeout(timer);
  }, [state.phase]);

  // Dismissing returns to idle AND hides the overlay window; Escape works too.
  useEffect(() => {
    if (state.phase === "idle") {
      void getCurrentWindow().hide();
      return;
    }
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") dismiss();
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [state.phase]);

  const listening = state.phase === "listening";
  const commandDetected =
    (state.phase === "listening" || state.phase === "processing") && state.commandDetected;

  return (
    <div className="pill-stage">
      <div className="pill">
        {state.phase === "idle" && (
          <span className="pill-idle-hint">
            <span className="pill-idle-dot" aria-hidden="true" />
            Hold F9
          </span>
        )}
        <PillWaveformCanvas active={listening} />
        {state.phase === "listening" || state.phase === "processing" ? (
          <HoldTimer startedAtMs={state.startedAtMs} />
        ) : (
          <span className="pill-timer pill-timer--idle">00:00</span>
        )}
        <span
          className={
            commandDetected
              ? "pill-mode-chip pill-mode-chip--command"
              : state.phase === "idle"
                ? "pill-mode-chip pill-mode-chip--idle"
                : "pill-mode-chip"
          }
        >
          {commandDetected ? "command" : "note"}
        </span>
      </div>

      {/* Command mode: mono echo of what was heard, live. commandDetected
          already narrows the phase to listening/processing (liveText holds). */}
      {commandDetected && "liveText" in state && (
        <div className="pill-echo">{state.liveText}</div>
      )}

      {state.phase === "result" && <ResultPopover final={state.final} />}

      {state.phase === "error" && (
        <div className="pill-popover" role="alert">
          <span className="pill-popover-label">Dictation error</span>
          <span className="pill-error-reason">{state.reason}</span>
          <div className="pill-popover-buttons">
            <button type="button" className="pill-button-ghost" onClick={dismiss}>
              Dismiss
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
