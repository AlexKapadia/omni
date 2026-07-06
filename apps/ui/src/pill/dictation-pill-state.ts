/**
 * The dictation pill's state machine — a PURE reducer, fully testable
 * without React, Tauri, or a socket.
 *
 * Phases follow design §07: idle (flat wave, "Hold F9") -> listening (live
 * wave + timer; chip flips to COMMAND when the wake word is heard) ->
 * processing (key released, awaiting the engine's final) -> result
 * (popover) | error. A new hold RESTARTS from any phase (double-press just
 * begins a fresh dictation); stale events for finished phases are dropped
 * (fail closed — an old final must never overwrite a new session).
 */

import type { DictationFinalPayload } from "./dictation-events-protocol";
import { detectOmniCommandPrefix } from "./omni-command-prefix-detector";

export type DictationPillState =
  | { readonly phase: "idle" }
  | {
      readonly phase: "listening";
      readonly startedAtMs: number;
      readonly liveText: string;
      readonly commandDetected: boolean;
    }
  | {
      readonly phase: "processing";
      readonly startedAtMs: number;
      readonly liveText: string;
      readonly commandDetected: boolean;
    }
  | { readonly phase: "result"; readonly final: DictationFinalPayload }
  | { readonly phase: "error"; readonly reason: string };

export type DictationPillEvent =
  | { readonly type: "hold-pressed"; readonly atMs: number }
  | { readonly type: "hold-released" }
  | { readonly type: "partial"; readonly text: string }
  | { readonly type: "final"; readonly payload: DictationFinalPayload }
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
      };

    case "hold-released":
      if (state.phase !== "listening") return state; // stray keyup: ignore
      return {
        phase: "processing",
        startedAtMs: state.startedAtMs,
        liveText: state.liveText,
        commandDetected: state.commandDetected,
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

    case "final":
      // Only a session that is actually awaiting a final may show one —
      // a stale final arriving in a NEW hold must not clobber it.
      if (state.phase !== "processing") return state;
      return { phase: "result", final: event.payload };

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
