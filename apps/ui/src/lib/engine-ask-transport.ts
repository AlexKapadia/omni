/**
 * REAL AskQueryTransport over the shared engine socket (reconciliation).
 *
 * Sends an `ask.query` command envelope and resolves the correlated
 * `ask.answer` REPLY payload (the engine's pinned reply name — NOT "ok", so
 * the meetings repository's ok-only correlator deliberately does not fit
 * here). Rejects honestly on the engine's `error` reply, on timeout, and
 * immediately when no socket is open (fail closed, no fake answers).
 *
 * Security invariant: every inbound frame is untrusted — it goes through
 * parseInboundMessage before any field is read; unrelated frames pass by.
 */
import { ASK_ANSWER_REPLY_NAME, ASK_QUERY_COMMAND_NAME, ENGINE_ASK_OFFLINE_MESSAGE } from "./engine-ask-answer-provider";
import type { AskQueryTransport } from "./engine-ask-answer-provider";
import { sendEngineEnvelope, subscribeToEngineFrames } from "./live-engine-socket";
import { makeCommand, parseInboundMessage, type Envelope } from "./protocol";

/** Injectable transport seam so unit tests drive the correlation with fakes. */
export interface EngineSocketTransport {
  sendEnvelope(envelope: Envelope): boolean;
  subscribeFrames(listener: (data: unknown) => void): () => void;
}

const liveSocket: EngineSocketTransport = {
  sendEnvelope: sendEngineEnvelope,
  subscribeFrames: subscribeToEngineFrames,
};

/** Retrieval is fast; synthesis runs a model call — match meeting chat (120s). */
export const ASK_REPLY_TIMEOUT_MS = 120_000;

/**
 * Build the transport the ask provider consumes. The reply must be named
 * `ask.answer` (resolved) or `error` (rejected with the engine's message);
 * any other reply name for our id is a protocol violation and rejects.
 */
export function createEngineAskTransport(
  socket: EngineSocketTransport = liveSocket,
  timeoutMs: number = ASK_REPLY_TIMEOUT_MS,
): AskQueryTransport {
  return {
    request: (name: string, payload: Record<string, unknown>) => {
      const envelope = makeCommand(name, payload);
      return new Promise<Record<string, unknown>>((resolve, reject) => {
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
          if (reply.name === ASK_ANSWER_REPLY_NAME) {
            finish(() => resolve(reply.payload));
            return;
          }
          // `error` (or anything else) is a refusal — surface the engine's
          // own plain-voice message, never a fabricated answer.
          const message = reply.payload["message"];
          finish(() =>
            reject(
              new Error(typeof message === "string" ? message : `engine replied ${reply.name}`),
            ),
          );
        });
        const timer = setTimeout(() => {
          finish(() => reject(new Error(`the engine did not answer ${name} in time`)));
        }, timeoutMs);
        if (!socket.sendEnvelope(envelope)) {
          finish(() => reject(new Error(ENGINE_ASK_OFFLINE_MESSAGE)));
        }
      });
    },
  };
}

// Re-exported so the wiring layer sends the pinned command name without
// importing the provider module twice.
export { ASK_QUERY_COMMAND_NAME };
