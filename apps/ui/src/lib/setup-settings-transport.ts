/**
 * Generic setup/settings transport over the shared engine socket, built on the
 * exact request/reply pattern of engine-ask-transport.ts: send a command
 * envelope, correlate the reply by envelope id, resolve on the engine's pinned
 * `ok` reply and reject honestly on `error`, on timeout, and immediately when
 * no socket is open (fail closed — never a fabricated success).
 *
 * It also exposes name-correlated EVENT subscriptions for the streaming
 * model-download and Google-connect flows, which are not single replies.
 *
 * Security invariant: every inbound frame is untrusted — it passes through
 * parseInboundMessage before any field is read; unrelated frames pass by.
 */
import { sendEngineEnvelope, subscribeToEngineFrames } from "./live-engine-socket";
import { makeCommand, parseInboundMessage, type Envelope } from "./protocol";
import {
  GOOGLE_CONNECT_COMPLETED_EVENT,
  MICROSOFT_CONNECT_COMPLETED_EVENT,
  MODELS_DOWNLOAD_COMPLETED_EVENT,
  MODELS_DOWNLOAD_FAILED_EVENT,
  MODELS_DOWNLOAD_PROGRESS_EVENT,
} from "./setup-settings-commands";
import {
  parseGoogleCompleted,
  parseModelsCompleted,
  parseModelsFailed,
  parseModelsProgress,
  type GoogleConnectCompleted,
  type ModelsDownloadCompleted,
  type ModelsDownloadFailed,
  type ModelsDownloadProgress,
} from "./models-download-events";

/** Injectable seam so unit tests drive the correlation with fakes. */
export interface EngineSocketTransport {
  sendEnvelope(envelope: Envelope): boolean;
  subscribeFrames(listener: (data: unknown) => void): () => void;
}

const liveSocket: EngineSocketTransport = {
  sendEnvelope: sendEngineEnvelope,
  subscribeFrames: subscribeToEngineFrames,
};

/** Honest offline copy, plain voice — no bot / marketing tone. */
export const ENGINE_SETUP_OFFLINE_MESSAGE =
  "The engine is not running. Setup needs the engine on this device.";

/** Reads are quick; a key validation makes a real 1-token call — bounded. */
export const SETUP_REPLY_TIMEOUT_MS = 30_000;

/**
 * Send one command and await its correlated `ok` reply payload. Rejects with
 * the engine's own plain-voice message on `error`, on timeout, and when no
 * socket is open. Any other reply name for our id is a protocol violation.
 */
export function requestSetupCommand(
  name: string,
  payload: Record<string, unknown> = {},
  timeoutMs: number = SETUP_REPLY_TIMEOUT_MS,
  socket: EngineSocketTransport = liveSocket,
): Promise<Record<string, unknown>> {
  const envelope = makeCommand(name, payload);
  return new Promise((resolve, reject) => {
    let settled = false;
    const finish = (settle: () => void): void => {
      if (settled) return;
      settled = true;
      unsubscribe();
      clearTimeout(timer);
      settle();
    };
    const unsubscribe = socket.subscribeFrames((data) => {
      const parsed = parseInboundMessage(data);
      // Unrelated frames (heartbeats, events, other replies) pass through.
      if (!parsed.ok || parsed.envelope.kind !== "reply") return;
      if (parsed.envelope.id !== envelope.id) return;
      const reply = parsed.envelope;
      if (reply.name === "ok") {
        finish(() => resolve(reply.payload));
        return;
      }
      // `error` (or anything else) is a refusal — surface the engine's message.
      const message = reply.payload["message"];
      finish(() =>
        reject(new Error(typeof message === "string" ? message : `engine replied ${reply.name}`)),
      );
    });
    const timer = setTimeout(() => {
      finish(() => reject(new Error(`the engine did not answer ${name} in time`)));
    }, timeoutMs);
    if (!socket.sendEnvelope(envelope)) {
      finish(() => reject(new Error(ENGINE_SETUP_OFFLINE_MESSAGE)));
    }
  });
}

/** Callbacks for the streaming model-download flow (all optional). */
export interface ModelsDownloadHandlers {
  readonly onProgress?: (progress: ModelsDownloadProgress) => void;
  readonly onFailed?: (failed: ModelsDownloadFailed) => void;
  readonly onCompleted?: (completed: ModelsDownloadCompleted) => void;
}

/**
 * Subscribe to the model-download events by name. Returns an unsubscribe. Each
 * event payload is validated fail-closed before a handler sees it — a corrupt
 * frame is dropped, never surfaced as bogus progress.
 */
export function subscribeToModelsDownload(
  handlers: ModelsDownloadHandlers,
  socket: EngineSocketTransport = liveSocket,
): () => void {
  return socket.subscribeFrames((data) => {
    const parsed = parseInboundMessage(data);
    if (!parsed.ok || parsed.envelope.kind !== "event") return;
    const { name, payload } = parsed.envelope;
    if (name === MODELS_DOWNLOAD_PROGRESS_EVENT) {
      const progress = parseModelsProgress(payload);
      if (progress !== null) handlers.onProgress?.(progress);
    } else if (name === MODELS_DOWNLOAD_FAILED_EVENT) {
      const failed = parseModelsFailed(payload);
      if (failed !== null) handlers.onFailed?.(failed);
    } else if (name === MODELS_DOWNLOAD_COMPLETED_EVENT) {
      const completed = parseModelsCompleted(payload);
      if (completed !== null) handlers.onCompleted?.(completed);
    }
  });
}

/** Subscribe to the single google.connect.completed event. */
export function subscribeToGoogleConnect(
  onCompleted: (completed: GoogleConnectCompleted) => void,
  socket: EngineSocketTransport = liveSocket,
): () => void {
  return socket.subscribeFrames((data) => {
    const parsed = parseInboundMessage(data);
    if (!parsed.ok || parsed.envelope.kind !== "event") return;
    if (parsed.envelope.name !== GOOGLE_CONNECT_COMPLETED_EVENT) return;
    const completed = parseGoogleCompleted(parsed.envelope.payload);
    if (completed !== null) onCompleted(completed);
  });
}

/** Subscribe to the single microsoft.connect.completed event. */
export function subscribeToMicrosoftConnect(
  onCompleted: (completed: GoogleConnectCompleted) => void,
  socket: EngineSocketTransport = liveSocket,
): () => void {
  return socket.subscribeFrames((data) => {
    const parsed = parseInboundMessage(data);
    if (!parsed.ok || parsed.envelope.kind !== "event") return;
    if (parsed.envelope.name !== MICROSOFT_CONNECT_COMPLETED_EVENT) return;
    const completed = parseGoogleCompleted(parsed.envelope.payload);
    if (completed !== null) onCompleted(completed);
  });
}
