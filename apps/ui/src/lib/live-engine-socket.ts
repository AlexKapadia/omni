/**
 * Live engine wiring: one WebSocket shared between the status layer and the
 * capture/transcript layer.
 *
 * engine-connection.ts owns reconnect/heartbeat logic and is consumed here
 * UNMODIFIED via its public createSocket option: we hand it a tee socket that
 * forwards every inbound frame to the capture event dispatcher before the
 * status logic sees it. One socket, two consumers, zero duplicated lifecycle.
 *
 * Security invariant: frames are parsed fail-closed (protocol.ts +
 * capture-protocol.ts); malformed or unknown events are dropped and never
 * mutate any store. Commands can only be sent over a socket that is OPEN —
 * otherwise sendEngineCommand refuses (fail closed) and returns false.
 */
import { EngineConnection, type WebSocketLike } from "./engine-connection";
import { makeCommand, parseInboundMessage } from "./protocol";
import {
  CAPTURE_DEVICE_CHANGED_EVENT_NAME,
  CAPTURE_STARTED_EVENT_NAME,
  CAPTURE_STOPPED_EVENT_NAME,
  TRANSCRIPT_FINAL_EVENT_NAME,
  TRANSCRIPT_PARTIAL_EVENT_NAME,
  parseCaptureDeviceChangedPayload,
  parseCaptureStartedPayload,
  parseCaptureStoppedPayload,
  parseTranscriptFinalPayload,
  parseTranscriptPartialPayload,
} from "./capture-protocol";
import {
  applyCaptureDeviceChanged,
  applyCaptureStarted,
  applyCaptureStopped,
  applyTranscriptFinal,
  applyTranscriptPartial,
  transcriptStore,
  type TranscriptStore,
} from "./transcript-store";

/**
 * Route one validated inbound frame to the transcript store. Exported as a
 * factory so tests drive an isolated store with raw frames.
 */
export function createCaptureEventDispatcher(
  store: TranscriptStore,
  now: () => number = () => Date.now(),
): (data: unknown) => void {
  return (data: unknown) => {
    const result = parseInboundMessage(data);
    if (!result.ok || result.envelope.kind !== "event") return; // fail closed
    const { name, payload } = result.envelope;
    if (name === TRANSCRIPT_FINAL_EVENT_NAME) {
      const parsed = parseTranscriptFinalPayload(payload);
      if (parsed !== null) applyTranscriptFinal(store, parsed);
    } else if (name === TRANSCRIPT_PARTIAL_EVENT_NAME) {
      const parsed = parseTranscriptPartialPayload(payload);
      if (parsed !== null) applyTranscriptPartial(store, parsed);
    } else if (name === CAPTURE_STARTED_EVENT_NAME) {
      const parsed = parseCaptureStartedPayload(payload);
      if (parsed !== null) applyCaptureStarted(store, parsed.meeting_id, now());
    } else if (name === CAPTURE_STOPPED_EVENT_NAME) {
      const parsed = parseCaptureStoppedPayload(payload);
      if (parsed !== null) applyCaptureStopped(store, parsed.meeting_id, parsed.reason);
    } else if (name === CAPTURE_DEVICE_CHANGED_EVENT_NAME) {
      const parsed = parseCaptureDeviceChangedPayload(payload);
      if (parsed !== null) applyCaptureDeviceChanged(store, parsed);
    }
    // Unknown events are ignored — deny by default, no speculative handling.
  };
}

/** The raw socket currently open, if any — the send path for commands. */
let activeSocket: WebSocket | null = null;
let appConnection: EngineConnection | null = null;

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
    activeSocket = inner; // command path is live only while this socket is
    tee.onopen?.();
  };
  inner.onmessage = (event) => {
    onFrame(event.data); // capture/transcript layer sees the frame first
    tee.onmessage?.({ data: event.data });
  };
  inner.onclose = () => {
    if (activeSocket === inner) activeSocket = null; // fail closed: no zombie sends
    tee.onclose?.();
  };
  inner.onerror = () => {
    if (activeSocket === inner) activeSocket = null;
    tee.onerror?.();
  };
  return tee;
}

/**
 * Start the app's single engine connection: status store + capture events.
 * Idempotent — safe under React StrictMode double-mount.
 */
export function startLiveEngineConnection(): void {
  if (appConnection !== null) {
    appConnection.start();
    return;
  }
  const dispatch = createCaptureEventDispatcher(transcriptStore);
  appConnection = new EngineConnection({
    createSocket: (url) => createTeeSocket(url, dispatch),
  });
  appConnection.start();
}

/**
 * Send one command envelope to the engine. Returns false (and sends nothing)
 * when no open socket exists — callers surface that honestly in the UI.
 */
export function sendEngineCommand(name: string, payload: Record<string, unknown> = {}): boolean {
  if (activeSocket === null || activeSocket.readyState !== WebSocket.OPEN) return false;
  try {
    activeSocket.send(JSON.stringify(makeCommand(name, payload)));
    return true;
  } catch {
    return false; // a torn socket is a refusal, not a crash
  }
}
