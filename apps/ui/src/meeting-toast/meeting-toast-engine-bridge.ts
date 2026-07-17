/**
 * Desktop meeting toast — isolated engine WebSocket feeding the detection
 * store used by the always-on-top overlay window.
 */
import { EngineConnection } from "../lib/engine-connection";
import { parseInboundMessage } from "../lib/protocol";
import {
  applyCaptureSuggestStop,
  applyMeetingDetected,
  CAPTURE_SUGGEST_STOP_EVENT_NAME,
  clearMeetingDetection,
  createMeetingDetectionStore,
  MEETING_DETECTED_EVENT_NAME,
  type MeetingDetectionStore,
} from "../lib/meeting-detection-store";
import { CAPTURE_STARTED_EVENT_NAME } from "../lib/capture-protocol";

/** Overlay-local store (not shared with the main window). */
export const meetingToastDetectionStore: MeetingDetectionStore = createMeetingDetectionStore();

let connection: EngineConnection | null = null;

function dispatchFrame(store: MeetingDetectionStore, data: unknown): void {
  const result = parseInboundMessage(data);
  if (!result.ok) return;
  const { name, payload } = result.message;
  if (name === MEETING_DETECTED_EVENT_NAME) {
    applyMeetingDetected(store, payload);
    return;
  }
  if (name === CAPTURE_SUGGEST_STOP_EVENT_NAME) {
    applyCaptureSuggestStop(store, payload);
    return;
  }
  if (name === CAPTURE_STARTED_EVENT_NAME) {
    clearMeetingDetection(store);
  }
}

/** Start the toast window's engine connection once at mount. */
export function startMeetingToastEngineBridge(
  store: MeetingDetectionStore = meetingToastDetectionStore,
): void {
  if (connection !== null) return;
  connection = new EngineConnection({
    createSocket: (url) => {
      const socket = new WebSocket(url);
      socket.addEventListener("message", (event) => dispatchFrame(store, event.data));
      return socket;
    },
  });
  connection.start();
}
