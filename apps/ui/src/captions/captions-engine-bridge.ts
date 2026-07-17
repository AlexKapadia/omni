/**
 * Captions overlay wiring: its own engine WebSocket feeding an isolated
 * transcript store (same dispatcher as the main live meeting screen).
 */
import { EngineConnection, type WebSocketLike } from "../lib/engine-connection";
import { createCaptureEventDispatcher } from "../lib/live-engine-socket";
import { createTranscriptStore, type TranscriptStore } from "../lib/transcript-store";

/** The overlay's isolated transcript store (not shared with the main window). */
export const captionsTranscriptStore: TranscriptStore = createTranscriptStore();

let connection: EngineConnection | null = null;

/** Tee a real WebSocket into WebSocketLike so EngineConnection can own lifecycle. */
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
    tee.onopen?.();
  };
  inner.onmessage = (event) => {
    onFrame(event.data);
    tee.onmessage?.({ data: event.data });
  };
  inner.onclose = () => {
    tee.onclose?.();
  };
  inner.onerror = () => {
    tee.onerror?.();
  };
  return tee;
}

/** Start the overlay's engine connection once at mount. */
export function startCaptionsEngineBridge(store: TranscriptStore = captionsTranscriptStore): void {
  if (connection !== null) return;
  const dispatch = createCaptureEventDispatcher(store);
  connection = new EngineConnection({
    createSocket: (url) => createTeeSocket(url, dispatch),
  });
  connection.start();
}
