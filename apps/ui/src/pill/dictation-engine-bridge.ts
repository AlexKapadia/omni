/**
 * The pill window's wiring: Tauri hold events + its own engine WebSocket.
 *
 * Reuses lib/engine-connection.ts UNMODIFIED via its createSocket seam (the
 * same tee pattern as lib/live-engine-socket.ts): one socket feeds both the
 * status logic and the dictation event dispatcher. The pill is a separate
 * webview, so this connection is independent of the main window's.
 *
 * Inject flow (Wispr-Flow-beating pillar): the shell captures the focused
 * window at KEYDOWN and says whether it is an external app; on release the
 * pill asks the engine for an inject-disposition final, and when that final
 * arrives it invokes the shell's `inject_dictation_text` command against
 * the keydown-captured target — never whatever happens to be focused later.
 * Release->text totals are stamped from REAL clocks (speed showcase).
 *
 * Fail-closed invariants: inbound frames are parsed fail-closed (malformed
 * frames never touch the store); commands are only sent over an OPEN socket
 * — an offline engine surfaces as an honest pill error, never a silent
 * dead session; a failed paste is reported with the text left on the
 * clipboard, never silently dropped.
 */
import { invoke } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";

import { EngineConnection, type WebSocketLike } from "../lib/engine-connection";
import { makeCommand, parseInboundMessage } from "../lib/protocol";
import {
  DICTATION_BEGIN_COMMAND_NAME,
  DICTATION_END_COMMAND_NAME,
  DICTATION_ERROR_EVENT_NAME,
  DICTATION_FINAL_EVENT_NAME,
  DICTATION_PARTIAL_EVENT_NAME,
  parseDictationErrorPayload,
  parseDictationFinalPayload,
  parseDictationPartialPayload,
} from "./dictation-events-protocol";
import { dispatchPillEvent, type DictationPillStore } from "./dictation-pill-store";

/** Rust-side event names (pinned in src-tauri/src/dictation_pill_window.rs). */
export const HOLD_PRESSED_TAURI_EVENT = "dictation-hold-pressed";
export const HOLD_RELEASED_TAURI_EVENT = "dictation-hold-released";

/** Payload the shell emits with hold-pressed (see dictation_pill_window.rs). */
export interface HoldPressedPayload {
  readonly inject_eligible: boolean;
  readonly target_hwnd: number;
}

/** Shell command result (pinned in src-tauri/src/dictation_text_injection.rs). */
interface InjectionOutcome {
  readonly ok: boolean;
  readonly elapsed_ms: number;
  readonly failure_reason: string | null;
}

/** Parse the shell's hold-pressed payload fail-closed (default: note mode). */
export function parseHoldPressedPayload(payload: unknown): HoldPressedPayload {
  if (typeof payload === "object" && payload !== null) {
    const record = payload as Record<string, unknown>;
    const eligible = record["inject_eligible"];
    const hwnd = record["target_hwnd"];
    if (typeof eligible === "boolean" && typeof hwnd === "number" && Number.isFinite(hwnd)) {
      return { inject_eligible: eligible, target_hwnd: hwnd };
    }
  }
  // Malformed shell payload -> the safe path: a note, never a paste.
  return { inject_eligible: false, target_hwnd: 0 };
}

/** The keydown-captured injection target for the CURRENT session. */
let currentTargetHwnd = 0;
/** Real release stamp for the honest release->text total (speed showcase). */
let releasedAtMs: number | null = null;

/**
 * Route one validated inbound frame into the pill store. Exported so tests
 * can drive an isolated store with raw frames. `performInjection` is a seam
 * so tests assert the paste leg without Tauri.
 */
export function createDictationEventDispatcher(
  store: DictationPillStore,
  performInjection: (text: string, targetHwnd: number) => Promise<InjectionOutcome> =
    invokeInjection,
): (data: unknown) => void {
  return (data: unknown) => {
    const result = parseInboundMessage(data);
    if (!result.ok || result.envelope.kind !== "event") return; // fail closed
    const { name, payload } = result.envelope;
    if (name === DICTATION_PARTIAL_EVENT_NAME) {
      const parsed = parseDictationPartialPayload(payload);
      if (parsed !== null) dispatchPillEvent(store, { type: "partial", text: parsed.text });
    } else if (name === DICTATION_FINAL_EVENT_NAME) {
      const parsed = parseDictationFinalPayload(payload);
      if (parsed === null) return;
      const totalMs = releasedAtMs !== null ? Date.now() - releasedAtMs : undefined;
      dispatchPillEvent(store, { type: "final", payload: parsed, totalMs });
      if (parsed.mode === "inject") {
        // Paste the CLEANED text (raw is retained engine-side); the target
        // is the keydown-captured window, never the current foreground.
        const textToInject = parsed.cleaned_text ?? parsed.text;
        const target = currentTargetHwnd;
        void performInjection(textToInject, target)
          .then((outcome) => {
            dispatchPillEvent(store, {
              type: "injection-result",
              ok: outcome.ok,
              elapsedMs: outcome.elapsed_ms,
              reason: outcome.failure_reason ?? undefined,
            });
          })
          .catch((error: unknown) => {
            // Honest failure: the text was NOT pasted; say so.
            dispatchPillEvent(store, {
              type: "injection-result",
              ok: false,
              reason: `insert failed: ${String(error)}`,
            });
          });
      }
    } else if (name === DICTATION_ERROR_EVENT_NAME) {
      const parsed = parseDictationErrorPayload(payload);
      if (parsed !== null) dispatchPillEvent(store, { type: "error", reason: parsed.reason });
    }
    // Unknown events are ignored — deny by default.
  };
}

/** The real Tauri command call (module-level so the seam can default to it). */
function invokeInjection(text: string, targetHwnd: number): Promise<InjectionOutcome> {
  return invoke<InjectionOutcome>("inject_dictation_text", { text, targetHwnd });
}

let activeSocket: WebSocket | null = null;
let pillConnection: EngineConnection | null = null;

function createTeeSocket(url: string, onFrame: (data: unknown) => void): WebSocketLike {
  const inner = new WebSocket(url);
  const tee: WebSocketLike = {
    onopen: null,
    onmessage: null,
    onclose: null,
    onerror: null,
    send: (data: string) => inner.send(data),
    close: () => inner.close(),
  };
  inner.onopen = () => {
    activeSocket = inner;
    tee.onopen?.();
  };
  inner.onmessage = (event) => {
    onFrame(event.data);
    tee.onmessage?.({ data: event.data });
  };
  inner.onclose = () => {
    if (activeSocket === inner) activeSocket = null; // no zombie sends
    tee.onclose?.();
  };
  inner.onerror = () => {
    if (activeSocket === inner) activeSocket = null;
    tee.onerror?.();
  };
  return tee;
}

/** Send one command; false (nothing sent) when the socket is not OPEN. */
function sendDictationCommand(name: string, payload: Record<string, unknown> = {}): boolean {
  if (activeSocket === null || activeSocket.readyState !== WebSocket.OPEN) return false;
  try {
    activeSocket.send(JSON.stringify(makeCommand(name, payload)));
    return true;
  } catch {
    return false; // a torn socket is a refusal, not a crash
  }
}

/**
 * Start the pill's engine connection and Tauri hold-key listeners.
 * Idempotent; returns an unlisten-cleanup for completeness (the pill window
 * lives for the whole app session).
 */
export function startDictationPillBridge(store: DictationPillStore): () => void {
  if (pillConnection === null) {
    const dispatch = createDictationEventDispatcher(store);
    pillConnection = new EngineConnection({
      createSocket: (url) => createTeeSocket(url, dispatch),
    });
  }
  pillConnection.start();

  const unlisteners: Array<() => void> = [];
  void listen(HOLD_PRESSED_TAURI_EVENT, (event) => {
    const pressed = parseHoldPressedPayload(event.payload);
    // Capture the injection target AT KEYDOWN — the window the user was
    // typing in — never whatever is foreground when the final arrives.
    currentTargetHwnd = pressed.target_hwnd;
    releasedAtMs = null;
    dispatchPillEvent(store, {
      type: "hold-pressed",
      atMs: Date.now(),
      injectEligible: pressed.inject_eligible,
    });
    if (!sendDictationCommand(DICTATION_BEGIN_COMMAND_NAME)) {
      // Honest failure: the pill must never pretend to be listening.
      dispatchPillEvent(store, {
        type: "error",
        reason: "Engine offline — dictation is unavailable",
      });
    }
  }).then((unlisten) => unlisteners.push(unlisten));
  void listen(HOLD_RELEASED_TAURI_EVENT, () => {
    // Read the disposition BEFORE reducing: the release event moves the
    // state to processing but must ship the arming as it stood at keyup.
    const state = store.getState();
    const injectRequested =
      state.phase === "listening" && state.injectArmed && !state.commandDetected;
    releasedAtMs = Date.now();
    dispatchPillEvent(store, { type: "hold-released" });
    if (
      !sendDictationCommand(DICTATION_END_COMMAND_NAME, {
        inject_requested: injectRequested,
      })
    ) {
      dispatchPillEvent(store, {
        type: "error",
        reason: "Engine connection lost — dictation was not saved",
      });
    }
  }).then((unlisten) => unlisteners.push(unlisten));

  return () => {
    for (const unlisten of unlisteners) unlisten();
  };
}
