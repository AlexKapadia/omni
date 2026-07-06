/**
 * User-initiated capture lifecycle: start / stop commands plus the optimistic
 * store transitions around them.
 *
 * Sits between the live meeting screen (caller) and live-engine-socket.ts
 * (wire). The engine's capture.started / capture.stopped events are the source
 * of truth; this layer only marks "starting"/"stopping" and surfaces honest
 * failures when the engine is unreachable (fail closed — no fake capture UI).
 */
import {
  CAPTURE_START_COMMAND_NAME,
  CAPTURE_STOP_COMMAND_NAME,
} from "./capture-protocol";
import { sendEngineCommand } from "./live-engine-socket";
import { transcriptStore, type TranscriptStore } from "./transcript-store";

export type CommandSender = (name: string, payload?: Record<string, unknown>) => boolean;

export const ENGINE_OFFLINE_MESSAGE =
  "The engine is offline. Capture needs the engine running on this device.";

export function requestCaptureStart(
  title?: string,
  store: TranscriptStore = transcriptStore,
  send: CommandSender = sendEngineCommand,
): boolean {
  const payload = title !== undefined && title.trim().length > 0 ? { title: title.trim() } : {};
  const sent = send(CAPTURE_START_COMMAND_NAME, payload);
  if (!sent) {
    // Fail closed: no engine, no capture — say so instead of pretending.
    store.setState({ captureStatus: "idle", errorMessage: ENGINE_OFFLINE_MESSAGE });
    return false;
  }
  store.setState({ captureStatus: "starting", errorMessage: null });
  return true;
}

export function requestCaptureStop(
  store: TranscriptStore = transcriptStore,
  send: CommandSender = sendEngineCommand,
): boolean {
  const sent = send(CAPTURE_STOP_COMMAND_NAME, {});
  if (!sent) {
    // Socket died mid-capture: the staleness detector will mark the engine
    // down; reflect the truth rather than a phantom "stopping" state.
    store.setState({ errorMessage: ENGINE_OFFLINE_MESSAGE });
    return false;
  }
  store.setState({ captureStatus: "stopping", errorMessage: null });
  return true;
}
