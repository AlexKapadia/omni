/**
 * The pill window's wiring: Tauri hold events + its own engine WebSocket.
 *
 * Reuses lib/engine-connection.ts UNMODIFIED via its createSocket seam (the
 * same tee pattern as lib/live-engine-socket.ts): one socket feeds both the
 * status logic and the dictation event dispatcher. The pill is a separate
 * webview, so this connection is independent of the main window's.
 *
 * Fail-closed invariants: inbound frames are parsed fail-closed (malformed
 * frames never touch the store); commands are only sent over an OPEN socket
 * — an offline engine surfaces as an honest pill error, never a silent
 * dead session.
 */
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

/**
 * Route one validated inbound frame into the pill store. Exported so tests
 * can drive an isolated store with raw frames.
 */
export function createDictationEventDispatcher(
  store: DictationPillStore,
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
      if (parsed !== null) dispatchPillEvent(store, { type: "final", payload: parsed });
    } else if (name === DICTATION_ERROR_EVENT_NAME) {
      const parsed = parseDictationErrorPayload(payload);
      if (parsed !== null) dispatchPillEvent(store, { type: "error", reason: parsed.reason });
    }
    // Unknown events are ignored — deny by default.
  };
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
function sendDictationCommand(name: string): boolean {
  if (activeSocket === null || activeSocket.readyState !== WebSocket.OPEN) return false;
  try {
    activeSocket.send(JSON.stringify(makeCommand(name)));
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
  void listen(HOLD_PRESSED_TAURI_EVENT, () => {
    dispatchPillEvent(store, { type: "hold-pressed", atMs: Date.now() });
    if (!sendDictationCommand(DICTATION_BEGIN_COMMAND_NAME)) {
      // Honest failure: the pill must never pretend to be listening.
      dispatchPillEvent(store, {
        type: "error",
        reason: "Engine offline — dictation is unavailable",
      });
    }
  }).then((unlisten) => unlisteners.push(unlisten));
  void listen(HOLD_RELEASED_TAURI_EVENT, () => {
    dispatchPillEvent(store, { type: "hold-released" });
    if (!sendDictationCommand(DICTATION_END_COMMAND_NAME)) {
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
