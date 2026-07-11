/**
 * Tray menu → engine bridge: "Start capture" emits a Tauri event the main
 * window listens for and translates into capture.start over the WebSocket.
 */
import { requestCaptureStart } from "./capture-commands";

const TRAY_START_CAPTURE_EVENT = "tray-start-capture";

export function wireTrayStartCapture(
  listen: (event: string, handler: () => void) => Promise<() => void>,
  onStart?: () => void,
): Promise<() => void> {
  return listen(TRAY_START_CAPTURE_EVENT, () => {
    onStart?.();
    requestCaptureStart();
  });
}
