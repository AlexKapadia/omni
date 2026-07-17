/**
 * Pill webview command channel: send + request/reply over the pill's own
 * engine WebSocket (the main-window live-engine-socket is not available here).
 */
import { makeCommand } from "../lib/protocol";
import { SETTINGS_GET_COMMAND } from "../lib/setup-settings-commands";
import { parseSettingsGet, type SettingsGetResult } from "../lib/setup-settings-payloads";

let activeSocket: WebSocket | null = null;

interface PendingReply {
  readonly resolve: (payload: Record<string, unknown>) => void;
  readonly reject: (error: Error) => void;
  readonly timer: ReturnType<typeof setTimeout>;
}

const pendingReplies = new Map<string, PendingReply>();
const PILL_REPLY_TIMEOUT_MS = 15_000;

/** Called by the bridge when the tee socket opens/closes. */
export function setPillActiveSocket(socket: WebSocket | null): void {
  activeSocket = socket;
}

/** Settle a correlated reply (called from the event dispatcher). */
export function settlePendingReply(
  id: string,
  name: string,
  payload: Readonly<Record<string, unknown>>,
): void {
  const pending = pendingReplies.get(id);
  if (pending === undefined) return;
  clearTimeout(pending.timer);
  pendingReplies.delete(id);
  if (name === "ok") {
    pending.resolve({ ...payload });
    return;
  }
  const message = payload["message"];
  pending.reject(
    new Error(typeof message === "string" ? message : `engine replied ${name}`),
  );
}

/** Send a command on the pill's own engine socket (Approve, dictation.*, …). */
export function sendDictationCommand(
  name: string,
  payload: Record<string, unknown> = {},
): boolean {
  if (activeSocket === null || activeSocket.readyState !== WebSocket.OPEN) return false;
  try {
    activeSocket.send(JSON.stringify(makeCommand(name, payload)));
    return true;
  } catch {
    return false;
  }
}

/**
 * Request/reply over the pill socket. Used for settings.get so the idle hint
 * shows the configured hotkey (main-window transport is not in this webview).
 */
export function requestPillCommand(
  name: string,
  payload: Record<string, unknown> = {},
  timeoutMs: number = PILL_REPLY_TIMEOUT_MS,
): Promise<Record<string, unknown>> {
  const envelope = makeCommand(name, payload);
  return new Promise((resolve, reject) => {
    if (activeSocket === null || activeSocket.readyState !== WebSocket.OPEN) {
      reject(new Error("Engine offline — pill socket is not open"));
      return;
    }
    const timer = setTimeout(() => {
      pendingReplies.delete(envelope.id);
      reject(new Error("Engine did not reply in time"));
    }, timeoutMs);
    pendingReplies.set(envelope.id, { resolve, reject, timer });
    try {
      activeSocket.send(JSON.stringify(envelope));
    } catch (error: unknown) {
      clearTimeout(timer);
      pendingReplies.delete(envelope.id);
      reject(error instanceof Error ? error : new Error(String(error)));
    }
  });
}

/** Fetch settings over the pill socket (retry until open or budget exhausted). */
export async function fetchPillSettings(
  budgetMs: number = 10_000,
): Promise<SettingsGetResult> {
  const deadline = Date.now() + budgetMs;
  let lastError: Error = new Error("Engine offline — pill socket is not open");
  while (Date.now() < deadline) {
    try {
      const payload = await requestPillCommand(SETTINGS_GET_COMMAND, {}, 4_000);
      const result = parseSettingsGet(payload);
      if (result === null) throw new Error("the engine sent malformed settings");
      return result;
    } catch (error: unknown) {
      lastError = error instanceof Error ? error : new Error(String(error));
      await new Promise((r) => setTimeout(r, 400));
    }
  }
  throw lastError;
}
