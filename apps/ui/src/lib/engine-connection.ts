/**
 * WebSocket client for the engine sidecar (protocol v1, see protocol.ts).
 *
 * Owns the socket lifecycle: connect, exponential-backoff reconnect, heartbeat
 * staleness detection, and ping/pong latency sampling. Publishes everything the
 * UI needs into an EngineStatusStore — components never touch the socket.
 *
 * Fail-closed invariants:
 * - status becomes "connected" only after a VALID heartbeat proves the engine
 *   is alive — an open socket alone is not proof.
 * - no heartbeat for HEARTBEAT_STALE_MS ⇒ "disconnected" and the socket is
 *   torn down for a fresh reconnect.
 * - malformed inbound frames are dropped (protocol.ts rejects them) and never
 *   mutate the store.
 */
import {
  ENGINE_WS_URL,
  HEARTBEAT_EVENT_NAME,
  PING_COMMAND_NAME,
  PONG_REPLY_NAME,
  makeCommand,
  parseHeartbeatPayload,
  parseInboundMessage,
} from "./protocol";
import { engineStatusStore, type EngineStatusStore } from "./engine-status-store";

/** Minimal surface we need from a WebSocket — lets tests inject a mock. */
export interface WebSocketLike {
  onopen: (() => void) | null;
  onmessage: ((event: { data: unknown }) => void) | null;
  onclose: (() => void) | null;
  onerror: (() => void) | null;
  send(data: string): void;
  close(): void;
}

export interface EngineConnectionOptions {
  readonly url?: string;
  readonly createSocket?: (url: string) => WebSocketLike;
  readonly store?: EngineStatusStore;
  /** Monotonic-ish clock in ms; injectable so tests control latency math. */
  readonly now?: () => number;
}

export const HEARTBEAT_STALE_MS = 5_000;
export const STALENESS_CHECK_INTERVAL_MS = 1_000;
export const PING_INTERVAL_MS = 10_000;
export const RECONNECT_BACKOFF_START_MS = 1_000;
export const RECONNECT_BACKOFF_MAX_MS = 30_000;

export class EngineConnection {
  private readonly url: string;
  private readonly createSocket: (url: string) => WebSocketLike;
  private readonly store: EngineStatusStore;
  private readonly now: () => number;

  private socket: WebSocketLike | null = null;
  private stopped = true;
  private socketOpen = false;
  private lastHeartbeatAt: number | null = null;
  private backoffMs = RECONNECT_BACKOFF_START_MS;
  private pendingPings = new Map<string, number>();
  private stalenessTimer: ReturnType<typeof setInterval> | null = null;
  private pingTimer: ReturnType<typeof setInterval> | null = null;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;

  constructor(options: EngineConnectionOptions = {}) {
    this.url = options.url ?? ENGINE_WS_URL;
    this.createSocket = options.createSocket ?? ((url) => new WebSocket(url) as unknown as WebSocketLike);
    this.store = options.store ?? engineStatusStore;
    this.now = options.now ?? (() => Date.now());
  }

  start(): void {
    if (!this.stopped) return; // idempotent — React StrictMode double-mounts effects
    this.stopped = false;
    this.connect();
  }

  stop(): void {
    this.stopped = true;
    this.clearTimers();
    this.teardownSocket();
  }

  private connect(): void {
    if (this.stopped) return;
    // Clear stale latency on every connect attempt so the footer hides ms
    // until a fresh pong arrives after reconnect.
    this.store.setState({ status: "connecting", lastLatencyMs: null });
    this.lastHeartbeatAt = null;
    let socket: WebSocketLike;
    try {
      socket = this.createSocket(this.url);
    } catch {
      // Constructor itself can throw (bad URL, no network stack) — treat like a drop.
      this.handleDrop();
      return;
    }
    this.socket = socket;
    socket.onopen = () => {
      // Socket up ≠ engine alive; stay "connecting" until a valid heartbeat.
      this.socketOpen = true;
      this.startStalenessTimer();
      this.startPingTimer();
      this.sendPing(); // sample latency immediately rather than waiting 10s
    };
    socket.onmessage = (event) => this.handleMessage(event.data);
    socket.onclose = () => this.handleDrop();
    socket.onerror = () => {
      // onerror is always followed by onclose per spec, but mocks and edge
      // cases may not honour that — treat error as a drop if still attached.
      if (this.socket === socket) this.handleDrop();
    };
  }

  private handleMessage(data: unknown): void {
    const result = parseInboundMessage(data);
    if (!result.ok) return; // fail closed: malformed frames never touch state
    const { envelope } = result;

    if (envelope.kind === "event" && envelope.name === HEARTBEAT_EVENT_NAME) {
      const heartbeat = parseHeartbeatPayload(envelope.payload);
      if (heartbeat === null) return; // corrupt heartbeat must not poison state
      this.lastHeartbeatAt = this.now();
      this.backoffMs = RECONNECT_BACKOFF_START_MS; // proven-alive resets backoff
      this.store.setState({
        status: "connected",
        uptimeS: heartbeat.uptime_s,
        engineVersion: heartbeat.engine_version,
        sttReady: heartbeat.stt_ready,
        sttEngine: heartbeat.stt_engine ?? null,
        sttDevice: heartbeat.stt_device ?? null,
      });
      return;
    }

    if (envelope.kind === "reply" && envelope.name === PONG_REPLY_NAME) {
      const sentAt = this.pendingPings.get(envelope.id);
      if (sentAt === undefined) return; // unknown/replayed id — ignore
      this.pendingPings.delete(envelope.id);
      this.store.setState({ lastLatencyMs: Math.max(0, this.now() - sentAt) });
    }
  }

  private sendPing(): void {
    if (!this.socket || !this.socketOpen) return;
    const command = makeCommand(PING_COMMAND_NAME);
    this.pendingPings.set(command.id, this.now());
    try {
      this.socket.send(JSON.stringify(command));
    } catch {
      this.pendingPings.delete(command.id);
    }
  }

  private startStalenessTimer(): void {
    this.stopTimer("staleness");
    this.stalenessTimer = setInterval(() => {
      if (this.lastHeartbeatAt === null) return; // still waiting for first heartbeat
      if (this.now() - this.lastHeartbeatAt > HEARTBEAT_STALE_MS) {
        // Engine went silent behind a live socket — declare it down and rebuild.
        this.store.setState({ status: "disconnected" });
        this.handleDrop();
      }
    }, STALENESS_CHECK_INTERVAL_MS);
  }

  private startPingTimer(): void {
    this.stopTimer("ping");
    this.pingTimer = setInterval(() => this.sendPing(), PING_INTERVAL_MS);
  }

  /** Socket lost (close/error/staleness): mark disconnected, back off, retry. */
  private handleDrop(): void {
    this.clearTimers();
    this.teardownSocket();
    if (this.stopped) return;
    // Stale RTT must not linger in the footer across a reconnect gap.
    this.store.setState({ status: "disconnected", lastLatencyMs: null });
    this.reconnectTimer = setTimeout(() => this.connect(), this.backoffMs);
    this.backoffMs = Math.min(this.backoffMs * 2, RECONNECT_BACKOFF_MAX_MS);
  }

  private teardownSocket(): void {
    const socket = this.socket;
    this.socket = null;
    this.socketOpen = false;
    this.pendingPings.clear();
    if (socket) {
      // Detach handlers first so this close can't re-enter handleDrop.
      socket.onopen = null;
      socket.onmessage = null;
      socket.onclose = null;
      socket.onerror = null;
      try {
        socket.close();
      } catch {
        /* already closed */
      }
    }
  }

  private clearTimers(): void {
    this.stopTimer("staleness");
    this.stopTimer("ping");
    if (this.reconnectTimer !== null) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
  }

  private stopTimer(which: "staleness" | "ping"): void {
    if (which === "staleness" && this.stalenessTimer !== null) {
      clearInterval(this.stalenessTimer);
      this.stalenessTimer = null;
    }
    if (which === "ping" && this.pingTimer !== null) {
      clearInterval(this.pingTimer);
      this.pingTimer = null;
    }
  }
}

/** App-lifetime singleton; created lazily so importing this module has no side effects. */
let appConnection: EngineConnection | null = null;

export function startEngineConnection(): EngineConnection {
  if (appConnection === null) appConnection = new EngineConnection();
  appConnection.start();
  return appConnection;
}
