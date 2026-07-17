/**
 * Desktop meeting toast — isolated engine WebSocket feeding the detection
 * store used by the always-on-top overlay window.
 */
import { EngineConnection, type WebSocketLike } from "../lib/engine-connection";
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
  const { name, payload } = result.envelope;
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

/** Start the toast window's engine connection once at mount. */
export function startMeetingToastEngineBridge(
  store: MeetingDetectionStore = meetingToastDetectionStore,
): void {
  if (connection !== null) return;
  connection = new EngineConnection({
    createSocket: (url) => createTeeSocket(url, (data) => dispatchFrame(store, data)),
  });
  connection.start();
}
