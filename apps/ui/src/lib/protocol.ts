/**
 * TypeScript mirror of the PINNED Omni WS protocol v1.
 *
 * The Python engine implements exactly this envelope; this file is the single
 * source of truth on the UI side. Sits between the raw WebSocket
 * (engine-connection.ts) and everything above it.
 *
 * Security invariant: every inbound frame is untrusted input. parseInboundMessage
 * is fail-closed — anything that does not match the envelope exactly is rejected
 * with a reason, never partially accepted or coerced.
 */

export const PROTOCOL_VERSION = 1 as const;

/** Engine WS endpoint — pinned; the engine binds loopback only (local-only invariant). */
export const ENGINE_WS_URL = "ws://127.0.0.1:8765/ws";

export type EnvelopeKind = "event" | "command" | "reply";

/** The v1 envelope shared by every message in both directions. */
export interface Envelope {
  readonly v: typeof PROTOCOL_VERSION;
  readonly kind: EnvelopeKind;
  readonly name: string;
  readonly id: string;
  readonly payload: Readonly<Record<string, unknown>>;
}

/** Engine → UI messages can only ever be events or replies; a "command" arriving
 *  inbound is a protocol violation and is rejected (fail closed). */
export type InboundEnvelope = Envelope & { readonly kind: "event" | "reply" };

/** Payload of the "engine.heartbeat" event the engine emits every 2s. */
export interface HeartbeatPayload {
  readonly uptime_s: number;
  readonly engine_version: string;
  readonly python: string;
  readonly stt_ready: boolean;
}

export const HEARTBEAT_EVENT_NAME = "engine.heartbeat";
export const PING_COMMAND_NAME = "ping";
export const PONG_REPLY_NAME = "pong";

export type ParseResult =
  | { readonly ok: true; readonly envelope: InboundEnvelope }
  | { readonly ok: false; readonly reason: string };

/** True only for a plain JSON object — arrays, null, class instances with
 *  exotic prototypes, and primitives all fail. Guards the payload contract. */
function isPlainObject(value: unknown): value is Record<string, unknown> {
  if (typeof value !== "object" || value === null || Array.isArray(value)) return false;
  const proto: unknown = Object.getPrototypeOf(value);
  return proto === Object.prototype || proto === null;
}

/**
 * Validate one raw inbound frame (string or already-parsed value) against the
 * pinned v1 envelope. Fail-closed: returns {ok:false, reason} on ANY deviation.
 */
export function parseInboundMessage(raw: unknown): ParseResult {
  let value: unknown = raw;
  if (typeof raw === "string") {
    try {
      value = JSON.parse(raw);
    } catch {
      return { ok: false, reason: "not valid JSON" };
    }
  }
  if (!isPlainObject(value)) {
    return { ok: false, reason: "envelope is not a plain object" };
  }
  // Exact version match — a v2 engine must not be half-understood by a v1 UI.
  if (value["v"] !== PROTOCOL_VERSION) {
    return { ok: false, reason: `unsupported protocol version: ${String(value["v"])}` };
  }
  const kind = value["kind"];
  if (kind !== "event" && kind !== "reply") {
    // "command" inbound is deliberately rejected — the UI issues commands, never receives them.
    return { ok: false, reason: `invalid inbound kind: ${String(kind)}` };
  }
  const name = value["name"];
  if (typeof name !== "string" || name.length === 0) {
    return { ok: false, reason: "name must be a non-empty string" };
  }
  const id = value["id"];
  if (typeof id !== "string" || id.length === 0) {
    return { ok: false, reason: "id must be a non-empty string" };
  }
  const payload = value["payload"];
  if (!isPlainObject(payload)) {
    return { ok: false, reason: "payload must be a plain object" };
  }
  return {
    ok: true,
    envelope: { v: PROTOCOL_VERSION, kind, name, id, payload },
  };
}

/**
 * Validate the heartbeat payload shape. Returns null on any type mismatch —
 * a heartbeat with a corrupt field must not poison the status store.
 */
export function parseHeartbeatPayload(payload: Record<string, unknown>): HeartbeatPayload | null {
  const uptime = payload["uptime_s"];
  const version = payload["engine_version"];
  const python = payload["python"];
  const sttReady = payload["stt_ready"];
  if (typeof uptime !== "number" || !Number.isFinite(uptime) || uptime < 0) return null;
  if (typeof version !== "string" || version.length === 0) return null;
  if (typeof python !== "string" || python.length === 0) return null;
  if (typeof sttReady !== "boolean") return null;
  return { uptime_s: uptime, engine_version: version, python, stt_ready: sttReady };
}

/** Build an outbound command envelope with a fresh correlation id. */
export function makeCommand(name: string, payload: Record<string, unknown> = {}): Envelope {
  return { v: PROTOCOL_VERSION, kind: "command", name, id: crypto.randomUUID(), payload };
}
