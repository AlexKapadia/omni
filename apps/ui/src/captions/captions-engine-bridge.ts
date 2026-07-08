/**
 * Captions overlay wiring: its own engine WebSocket feeding an isolated
 * transcript store (same dispatcher as the main live meeting screen).
 */
import { EngineConnection } from "../lib/engine-connection";
import { createCaptureEventDispatcher } from "../lib/live-engine-socket";
import { createTranscriptStore, type TranscriptStore } from "../lib/transcript-store";

/** The overlay's isolated transcript store (not shared with the main window). */
export const captionsTranscriptStore: TranscriptStore = createTranscriptStore();

let connection: EngineConnection | null = null;

/** Start the overlay's engine connection once at mount. */
export function startCaptionsEngineBridge(store: TranscriptStore = captionsTranscriptStore): void {
  if (connection !== null) return;
  const dispatch = createCaptureEventDispatcher(store);
  connection = new EngineConnection({
    createSocket: (url) => {
      const socket = new WebSocket(url);
      socket.addEventListener("message", (event) => dispatch(event.data));
      return socket;
    },
  });
  connection.start();
}
