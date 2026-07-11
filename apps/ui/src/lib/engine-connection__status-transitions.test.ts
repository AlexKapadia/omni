/**
 * State-machine tests for EngineConnection against a mock WebSocket + fake
 * timers. These are transition tests, not smoke tests: they assert WHEN status
 * flips (heartbeat proof, staleness cutoff, backoff schedule), not just that
 * the class constructs.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { EngineConnection, HEARTBEAT_STALE_MS, type WebSocketLike } from "./engine-connection";
import { createEngineStatusStore, type EngineStatusStore } from "./engine-status-store";

class MockSocket implements WebSocketLike {
  onopen: (() => void) | null = null;
  onmessage: ((event: { data: unknown }) => void) | null = null;
  onclose: (() => void) | null = null;
  onerror: (() => void) | null = null;
  sent: string[] = [];
  closed = false;
  send(data: string): void {
    this.sent.push(data);
  }
  close(): void {
    this.closed = true;
  }
  open(): void {
    this.onopen?.();
  }
  receive(frame: unknown): void {
    this.onmessage?.({ data: typeof frame === "string" ? frame : JSON.stringify(frame) });
  }
  drop(): void {
    this.onclose?.();
  }
}

function heartbeat(uptimeS = 1): Record<string, unknown> {
  return {
    v: 1,
    kind: "event",
    name: "engine.heartbeat",
    id: `hb-${uptimeS}`,
    payload: { uptime_s: uptimeS, engine_version: "0.1.0", python: "3.12.4", stt_ready: false },
  };
}

let sockets: MockSocket[];
let store: EngineStatusStore;
let connection: EngineConnection;

function lastSocket(): MockSocket {
  const socket = sockets[sockets.length - 1];
  if (socket === undefined) throw new Error("no socket created yet");
  return socket;
}

beforeEach(() => {
  vi.useFakeTimers();
  sockets = [];
  store = createEngineStatusStore();
  connection = new EngineConnection({
    store,
    createSocket: () => {
      const socket = new MockSocket();
      sockets.push(socket);
      return socket;
    },
  });
});

afterEach(() => {
  connection.stop();
  vi.useRealTimers();
});

describe("EngineConnection status transitions", () => {
  it("starts in 'connecting' and stays there while the socket is open but silent", () => {
    connection.start();
    expect(store.getState().status).toBe("connecting");
    lastSocket().open();
    // An open socket is NOT proof the engine is alive (fail closed).
    expect(store.getState().status).toBe("connecting");
  });

  it("becomes 'connected' only after a VALID heartbeat", () => {
    connection.start();
    lastSocket().open();
    // Malformed frames first — none of these may flip the status.
    lastSocket().receive("{broken json");
    lastSocket().receive({ v: 2, kind: "event", name: "engine.heartbeat", id: "x", payload: {} });
    lastSocket().receive({ v: 1, kind: "command", name: "ping", id: "x", payload: {} });
    lastSocket().receive({ v: 1, kind: "event", name: "engine.heartbeat", id: "x", payload: { uptime_s: "5" } });
    expect(store.getState().status).toBe("connecting");

    lastSocket().receive(heartbeat(7));
    expect(store.getState().status).toBe("connected");
    expect(store.getState().uptimeS).toBe(7);
    expect(store.getState().engineVersion).toBe("0.1.0");
  });

  it("declares 'disconnected' when heartbeats go stale past the 5s cutoff", () => {
    connection.start();
    lastSocket().open();
    lastSocket().receive(heartbeat());
    expect(store.getState().status).toBe("connected");

    // Just UNDER the cutoff: still connected (boundary check).
    vi.advanceTimersByTime(HEARTBEAT_STALE_MS - 1000);
    expect(store.getState().status).toBe("connected");

    // Past the cutoff: staleness checker must flip to disconnected and tear down.
    const staleSocket = lastSocket();
    vi.advanceTimersByTime(2000);
    expect(store.getState().status).toBe("disconnected");
    expect(staleSocket.closed).toBe(true);
  });

  it("fresh heartbeats keep the connection alive indefinitely", () => {
    connection.start();
    lastSocket().open();
    for (let tick = 0; tick < 10; tick += 1) {
      lastSocket().receive(heartbeat(tick));
      vi.advanceTimersByTime(2000); // engine heartbeats every 2s
      expect(store.getState().status).toBe("connected");
    }
  });

  it("reconnects with exponential backoff 1s, 2s, 4s after repeated drops", () => {
    connection.start();
    expect(sockets.length).toBe(1);

    lastSocket().drop();
    expect(store.getState().status).toBe("disconnected");
    vi.advanceTimersByTime(999);
    expect(sockets.length).toBe(1); // not yet — backoff is 1s
    vi.advanceTimersByTime(1);
    expect(sockets.length).toBe(2);
    expect(store.getState().status).toBe("connecting");

    lastSocket().drop();
    vi.advanceTimersByTime(1999);
    expect(sockets.length).toBe(2); // not yet — backoff doubled to 2s
    vi.advanceTimersByTime(1);
    expect(sockets.length).toBe(3);

    lastSocket().drop();
    vi.advanceTimersByTime(3999);
    expect(sockets.length).toBe(3); // 4s now
    vi.advanceTimersByTime(1);
    expect(sockets.length).toBe(4);
  });

  it("caps reconnect backoff at 30s", () => {
    connection.start();
    // Burn through 1,2,4,8,16 → next delay would be 32s but must cap at 30s.
    for (const delay of [1000, 2000, 4000, 8000, 16000]) {
      lastSocket().drop();
      vi.advanceTimersByTime(delay);
    }
    const socketCount = sockets.length;
    lastSocket().drop();
    vi.advanceTimersByTime(29_999);
    expect(sockets.length).toBe(socketCount);
    vi.advanceTimersByTime(1);
    expect(sockets.length).toBe(socketCount + 1);
  });

  it("a valid heartbeat resets the backoff to 1s", () => {
    connection.start();
    lastSocket().drop(); // backoff now 2s pending
    vi.advanceTimersByTime(1000);
    lastSocket().drop();
    vi.advanceTimersByTime(2000);

    lastSocket().open();
    lastSocket().receive(heartbeat());
    expect(store.getState().status).toBe("connected");

    const socketCount = sockets.length;
    lastSocket().drop();
    vi.advanceTimersByTime(1000); // back to the 1s starting delay
    expect(sockets.length).toBe(socketCount + 1);
  });

  it("measures ping/pong round-trip latency and ignores unknown pong ids", () => {
    connection.start();
    lastSocket().open();
    // A ping is sent immediately on open.
    expect(lastSocket().sent.length).toBe(1);
    const sentRaw = lastSocket().sent[0];
    if (sentRaw === undefined) throw new Error("ping not sent");
    const ping = JSON.parse(sentRaw) as { kind: string; name: string; id: string };
    expect(ping.kind).toBe("command");
    expect(ping.name).toBe("ping");

    // Pong with a WRONG id must be ignored.
    lastSocket().receive({ v: 1, kind: "reply", name: "pong", id: "not-the-id", payload: {} });
    expect(store.getState().lastLatencyMs).toBeNull();

    // Pong with the right id after 37ms → latency 37ms.
    vi.advanceTimersByTime(37);
    lastSocket().receive({ v: 1, kind: "reply", name: "pong", id: ping.id, payload: {} });
    expect(store.getState().lastLatencyMs).toBe(37);

    // A replayed pong (same id again) must not update anything.
    vi.advanceTimersByTime(500);
    lastSocket().receive({ v: 1, kind: "reply", name: "pong", id: ping.id, payload: {} });
    expect(store.getState().lastLatencyMs).toBe(37);
  });

  it("clears lastLatencyMs on disconnect so the footer never shows stale latency", () => {
    connection.start();
    lastSocket().open();
    const sentRaw = lastSocket().sent[0];
    if (sentRaw === undefined) throw new Error("ping not sent");
    const ping = JSON.parse(sentRaw) as { id: string };
    vi.advanceTimersByTime(12);
    lastSocket().receive({ v: 1, kind: "reply", name: "pong", id: ping.id, payload: {} });
    expect(store.getState().lastLatencyMs).toBe(12);

    lastSocket().drop();
    expect(store.getState().status).toBe("disconnected");
    expect(store.getState().lastLatencyMs).toBeNull();

    // Reconnect start also keeps latency cleared until a fresh pong.
    vi.advanceTimersByTime(1000);
    expect(store.getState().status).toBe("connecting");
    expect(store.getState().lastLatencyMs).toBeNull();
  });

  it("keeps pinging on the 10s interval while connected", () => {
    connection.start();
    lastSocket().open();
    lastSocket().receive(heartbeat());
    const socket = lastSocket();
    expect(socket.sent.length).toBe(1);
    // Keep heartbeats fresh while advancing so staleness never interferes.
    for (let elapsed = 2000; elapsed <= 10_000; elapsed += 2000) {
      vi.advanceTimersByTime(2000);
      socket.receive(heartbeat(elapsed / 1000));
    }
    expect(socket.sent.length).toBe(2);
  });

  it("stop() closes the socket and never reconnects", () => {
    connection.start();
    lastSocket().open();
    connection.stop();
    expect(lastSocket().closed).toBe(true);
    vi.advanceTimersByTime(120_000);
    expect(sockets.length).toBe(1);
  });

  it("start() is idempotent — a second call must not open a second socket", () => {
    connection.start();
    connection.start();
    expect(sockets.length).toBe(1);
  });

  it("survives a createSocket factory that throws, and keeps retrying", () => {
    const failing = new EngineConnection({
      store,
      createSocket: () => {
        throw new Error("no network stack");
      },
    });
    failing.start();
    expect(store.getState().status).toBe("disconnected");
    vi.advanceTimersByTime(1000); // must schedule a retry, not crash
    expect(store.getState().status).toBe("disconnected");
    failing.stop();
  });
});
