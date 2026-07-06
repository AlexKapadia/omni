/**
 * The dictation pill — design §07, every state real:
 * idle (flat wave · 00:00 grey · NOTE ghost · breathing dot + "Hold F9"),
 * listening (live wave · running timer · ink chip; chip inverts to COMMAND
 * on the wake word; chip reads INSERT when an external app is the target
 * and is CLICKABLE to flip back to NOTE before release), processing,
 * result popover (note saved / intent recorded / text inserted — with the
 * REAL measured latencies, mono, speed-showcase mandate), and error — all
 * driven by the store.
 */
import { useEffect, useState } from "react";
import { getCurrentWindow } from "@tauri-apps/api/window";

import type { DictationFinalPayload } from "./dictation-events-protocol";
import {
  RESULT_AUTO_DISMISS_MS,
  formatHoldTimer,
  formatLatencyMs,
  type PillInjectionStatus,
} from "./dictation-pill-state";
import { dictationPillStore, dispatchPillEvent, usePillState } from "./dictation-pill-store";
import { PillWaveformCanvas } from "./pill-waveform-canvas";

/** Build the obsidian:// URI for a saved Inbox note from its file path. */
export function obsidianOpenUriFromNotePath(notePath: string): string {
  const basename = notePath.split(/[\\/]/).pop() ?? notePath;
  const stem = basename.replace(/\.md$/, "");
  return `obsidian://open?file=${encodeURIComponent(`Inbox/${stem}`)}`;
}

/**
 * The honest per-stage latency line: only REAL measured numbers appear;
 * absent stamps are simply not shown (never invented).
 */
export function buildLatencyLine(
  final: DictationFinalPayload,
  totalMs?: number | undefined,
  injectionMs?: number | undefined,
): string {
  const parts: string[] = [];
  if (final.flush_ms !== undefined) parts.push(`stt ${formatLatencyMs(final.flush_ms)}`);
  if (final.cleanup_latency_ms !== undefined) {
    parts.push(`clean ${formatLatencyMs(final.cleanup_latency_ms)}`);
  }
  if (injectionMs !== undefined) parts.push(`insert ${formatLatencyMs(injectionMs)}`);
  if (totalMs !== undefined) parts.push(`total ${formatLatencyMs(totalMs)}`);
  return parts.join(" · ");
}

function dismiss(): void {
  dispatchPillEvent(dictationPillStore, { type: "dismiss" });
}

function flipToNote(): void {
  dispatchPillEvent(dictationPillStore, { type: "flip-to-note" });
}

function HoldTimer({ startedAtMs }: { readonly startedAtMs: number }) {
  const [nowMs, setNowMs] = useState(() => Date.now());
  useEffect(() => {
    const timer = setInterval(() => setNowMs(Date.now()), 250);
    return () => clearInterval(timer);
  }, []);
  return <span className="pill-timer">{formatHoldTimer(nowMs - startedAtMs)}</span>;
}

function LatencyLine({
  final,
  totalMs,
  injectionMs,
}: {
  readonly final: DictationFinalPayload;
  readonly totalMs?: number | undefined;
  readonly injectionMs?: number | undefined;
}) {
  const line = buildLatencyLine(final, totalMs, injectionMs);
  if (line === "") return null;
  return <span className="pill-popover-latency">{line}</span>;
}

function InjectResultPopover({
  final,
  totalMs,
  injection,
}: {
  readonly final: DictationFinalPayload;
  readonly totalMs?: number | undefined;
  readonly injection?: PillInjectionStatus | undefined;
}) {
  const pasted = final.cleaned_text ?? final.text;
  const label =
    injection === undefined || injection.status === "pending"
      ? "Inserting…"
      : injection.status === "done"
        ? "Inserted"
        : "Couldn't insert";
  return (
    <div className="pill-popover" role="status">
      <span className="pill-popover-label">{label}</span>
      <span className="pill-popover-quote">“{pasted}”</span>
      {injection?.status === "failed" && (
        // Honest failure: name the reason; the text stays on the clipboard
        // so the words are one manual Ctrl+V away, never lost.
        <span className="pill-popover-detail">{injection.reason}</span>
      )}
      {final.cleanup_source === "raw_fallback" && final.degraded_reason !== undefined && (
        <span className="pill-popover-detail">{final.degraded_reason}</span>
      )}
      <LatencyLine
        final={final}
        totalMs={totalMs}
        injectionMs={injection?.status === "done" ? injection.elapsedMs : undefined}
      />
      <div className="pill-popover-buttons">
        <button type="button" className="pill-button-ghost" onClick={dismiss}>
          Dismiss
        </button>
      </div>
    </div>
  );
}

function ResultPopover({
  final,
  totalMs,
  injection,
}: {
  readonly final: DictationFinalPayload;
  readonly totalMs?: number | undefined;
  readonly injection?: PillInjectionStatus | undefined;
}) {
  if (final.mode === "inject") {
    return <InjectResultPopover final={final} totalMs={totalMs} injection={injection} />;
  }
  if (final.mode === "note") {
    return (
      <div className="pill-popover" role="status">
        <span className="pill-popover-label">
          {final.title_source === "fallback" ? "Note saved · offline title" : "Note saved"}
        </span>
        {/* The body the note actually carries: cleaned when cleanup ran. */}
        <span className="pill-popover-quote">“{final.cleaned_text ?? final.text}”</span>
        <span className="pill-popover-title">{final.note_title ?? "Untitled"}</span>
        {final.cleanup_source === "model" && (
          <span className="pill-popover-detail">Raw transcript kept inside the note.</span>
        )}
        {final.degraded_reason !== undefined && (
          <span className="pill-popover-detail">{final.degraded_reason}</span>
        )}
        <LatencyLine final={final} totalMs={totalMs} />
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
      <LatencyLine final={final} totalMs={totalMs} />
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

  // Result popovers self-dismiss — but never while a paste is still in
  // flight (dismissing a pending injection would hide its honest outcome).
  const injectionStatus = state.phase === "result" ? state.injection?.status : undefined;
  useEffect(() => {
    if (state.phase !== "result" && state.phase !== "error") return;
    if (injectionStatus === "pending") return;
    const timer = setTimeout(dismiss, RESULT_AUTO_DISMISS_MS);
    return () => clearTimeout(timer);
  }, [state.phase, injectionStatus]);

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
  const inSession = state.phase === "listening" || state.phase === "processing";
  const commandDetected = inSession && state.commandDetected;
  const injectArmed = inSession && !state.commandDetected && state.injectArmed;

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
        {inSession ? (
          <HoldTimer startedAtMs={state.startedAtMs} />
        ) : (
          <span className="pill-timer pill-timer--idle">00:00</span>
        )}
        {injectArmed && listening ? (
          // The flip affordance: INSERT is a real control while the key is
          // held — one click redirects this dictation into a vault note.
          <button
            type="button"
            className="pill-mode-chip pill-mode-chip--insert"
            onClick={flipToNote}
            title="Save as a note instead"
          >
            insert
          </button>
        ) : (
          <span
            className={
              commandDetected
                ? "pill-mode-chip pill-mode-chip--command"
                : injectArmed
                  ? "pill-mode-chip pill-mode-chip--insert"
                  : state.phase === "idle"
                    ? "pill-mode-chip pill-mode-chip--idle"
                    : "pill-mode-chip"
            }
          >
            {commandDetected ? "command" : injectArmed ? "insert" : "note"}
          </span>
        )}
      </div>

      {/* Command mode: mono echo of what was heard, live. commandDetected
          already narrows the phase to listening/processing (liveText holds). */}
      {commandDetected && "liveText" in state && (
        <div className="pill-echo">{state.liveText}</div>
      )}

      {state.phase === "result" && (
        <ResultPopover
          final={state.final}
          totalMs={state.totalMs}
          injection={state.injection}
        />
      )}

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
