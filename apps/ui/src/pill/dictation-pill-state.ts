/**
 * The dictation pill's state machine — a PURE reducer, fully testable
 * without React, Tauri, or a socket.
 *
 * Phases follow design §07: idle (flat wave, "Hold F9") -> listening (live
 * wave + timer; chip flips to COMMAND when the wake word is heard; chip
 * shows INSERT when an external app was focused at keydown, flippable to
 * NOTE before release) -> processing (key released, awaiting the engine's
 * final) -> result (popover; inject results track the paste round-trip) |
 * error. A new hold RESTARTS from any phase (double-press just begins a
 * fresh dictation); stale events for finished phases are dropped (fail
 * closed — an old final must never overwrite a new session).
 */

import type { DictationFinalPayload } from "./dictation-events-protocol";
import { detectOmniCommandPrefix } from "./omni-command-prefix-detector";

/** The paste round-trip, tracked honestly in the result phase. */
export type PillInjectionStatus =
  | { readonly status: "pending" }
  | { readonly status: "done"; readonly elapsedMs: number }
  | { readonly status: "failed"; readonly reason: string };

export type DictationPillState =
  | { readonly phase: "idle" }
  | {
      readonly phase: "listening";
      readonly startedAtMs: number;
      readonly liveText: string;
      readonly commandDetected: boolean;
      readonly injectArmed: boolean;
      readonly lockedRecording?: boolean;
    }
  | {
      readonly phase: "processing";
      readonly startedAtMs: number;
      readonly liveText: string;
      readonly commandDetected: boolean;
      readonly injectArmed: boolean;
      readonly lockedRecording?: boolean;
    }
  | {
      readonly phase: "result";
      readonly final: DictationFinalPayload;
      /** Real measured release->final wall time (speed showcase), if known. */
      readonly totalMs?: number;
      /** Present only for inject finals — the paste is still in flight. */
      readonly injection?: PillInjectionStatus;
    }
  | { readonly phase: "error"; readonly reason: string };

export type DictationPillEvent =
  | {
      readonly type: "hold-pressed";
      readonly atMs: number;
      /** From the shell: an external (non-Omni) window was focused at
       * keydown, so the default disposition is INJECT. Absent = false. */
      readonly injectEligible?: boolean;
    }
  | { readonly type: "hold-released" }
  | { readonly type: "partial"; readonly text: string }
  /** Pill affordance: flip the armed INSERT back to NOTE before release. */
  | { readonly type: "flip-to-note" }
  | { readonly type: "lock-engaged" }
  | {
      readonly type: "final";
      readonly payload: DictationFinalPayload;
      readonly totalMs?: number | undefined;
    }
  | {
      readonly type: "injection-result";
      readonly ok: boolean;
      readonly elapsedMs?: number | undefined;
      readonly reason?: string | undefined;
    }
  | { readonly type: "error"; readonly reason: string }
  | { readonly type: "dismiss" };

export const IDLE_PILL_STATE: DictationPillState = { phase: "idle" };

/** Result popover lifetime before auto-dismiss (view enforces it). */
export const RESULT_AUTO_DISMISS_MS = 8_000;

export function reduceDictationPill(
  state: DictationPillState,
  event: DictationPillEvent,
): DictationPillState {
  switch (event.type) {
    case "hold-pressed":
      // From ANY phase: a fresh hold is a fresh dictation (double-press,
      // press-during-result, press-during-error all restart cleanly).
      return {
        phase: "listening",
        startedAtMs: event.atMs,
        liveText: "",
        commandDetected: false,
        injectArmed: event.injectEligible === true, // absent/false -> note
      };

    case "hold-released":
      if (state.phase !== "listening") return state; // stray keyup: ignore
      return {
        phase: "processing",
        startedAtMs: state.startedAtMs,
        liveText: state.liveText,
        commandDetected: state.commandDetected,
        injectArmed: state.injectArmed,
        ...(state.lockedRecording ? { lockedRecording: true } : {}),
      };

    case "partial":
      // Partials only matter while the key is held; a late partial after
      // release may still arrive while processing — accept it there too so
      // the echoed text stays current, but never resurrect a finished pill.
      if (state.phase !== "listening" && state.phase !== "processing") return state;
      return {
        ...state,
        liveText: event.text,
        commandDetected: detectOmniCommandPrefix(event.text),
      };

    case "flip-to-note":
      if (state.phase !== "listening") return state;
      return { ...state, injectArmed: false };

    case "lock-engaged":
      if (state.phase !== "listening") return state;
      return { ...state, lockedRecording: true };

    case "final":
      // Only a session that is actually awaiting a final may show one —
      // a stale final arriving in a NEW hold must not clobber it.
      if (state.phase !== "processing") return state;
      return {
        phase: "result",
        final: event.payload,
        ...(event.totalMs !== undefined ? { totalMs: event.totalMs } : {}),
        // Inject finals wait for the shell's paste round-trip; anything
        // else has no injection leg at all.
        ...(event.payload.mode === "inject"
          ? { injection: { status: "pending" as const } }
          : {}),
      };

    case "injection-result": {
      // Applies only to the result that is actually awaiting a paste —
      // a stale injection outcome must never relabel a newer result.
      if (state.phase !== "result" || state.injection?.status !== "pending") return state;
      const injection: PillInjectionStatus = event.ok
        ? { status: "done", elapsedMs: event.elapsedMs ?? 0 }
        : {
            status: "failed",
            reason: event.reason ?? "insert failed — text left on the clipboard",
          };
      return { ...state, injection };
    }

    case "error":
      if (state.phase !== "listening" && state.phase !== "processing") return state;
      return { phase: "error", reason: event.reason };

    case "dismiss":
      return IDLE_PILL_STATE;
  }
}

/** mm:ss for the mono timer, exact to the second, never negative. */
export function formatHoldTimer(elapsedMs: number): string {
  const totalSeconds = Math.max(0, Math.floor(elapsedMs / 1000));
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  return `${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}`;
}

/** "812 ms" / "1.24 s" — honest, compact latency label (speed showcase). */
export function formatLatencyMs(ms: number): string {
  const rounded = Math.max(0, Math.round(ms));
  if (rounded < 1000) return `${rounded} ms`;
  return `${(rounded / 1000).toFixed(2)} s`;
}
