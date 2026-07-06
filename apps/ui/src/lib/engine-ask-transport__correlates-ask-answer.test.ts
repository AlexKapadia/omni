/**
 * Ask transport tests: the request/reply correlator behind the real Ask
 * screen — resolves ONLY the correlated `ask.answer` reply, rejects on the
 * engine's `error` reply with its own message, rejects unexpected reply
 * names, times out honestly, and refuses immediately when no socket exists.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  ASK_REPLY_TIMEOUT_MS,
  createEngineAskTransport,
  type EngineSocketTransport,
} from "./engine-ask-transport";
import type { Envelope } from "./protocol";

class FakeSocket implements EngineSocketTransport {
  sent: Envelope[] = [];
  online = true;
  private listeners = new Set<(data: unknown) => void>();

  sendEnvelope(envelope: Envelope): boolean {
    if (!this.online) return false;
    this.sent.push(envelope);
    return true;
  }

  subscribeFrames(listener: (data: unknown) => void): () => void {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }

  deliver(frame: Record<string, unknown>): void {
    for (const listener of [...this.listeners]) listener(JSON.stringify(frame));
  }

  reply(id: string, name: string, payload: Record<string, unknown>): void {
    this.deliver({ v: 1, kind: "reply", name, id, payload });
  }
}

beforeEach(() => {
  vi.useFakeTimers();
});

afterEach(() => {
  vi.useRealTimers();
});

describe("createEngineAskTransport", () => {
  it("sends ask.query and resolves the correlated ask.answer payload", async () => {
    const socket = new FakeSocket();
    const transport = createEngineAskTransport(socket);
    const pending = transport.request("ask.query", { query: "who owns the budget?" });
    expect(socket.sent).toHaveLength(1);
    const envelope = socket.sent[0]!;
    expect(envelope.name).toBe("ask.query");
    expect(envelope.payload).toEqual({ query: "who owns the budget?" });
    // Unrelated traffic passes by: heartbeats, events, replies for others.
    socket.deliver({ v: 1, kind: "event", name: "engine.heartbeat", id: "h", payload: {} });
    socket.reply("someone-else", "ask.answer", { headline: "not ours" });
    socket.reply(envelope.id, "ask.answer", { headline: "Budget owner" });
    await expect(pending).resolves.toEqual({ headline: "Budget owner" });
  });

  it("rejects with the engine's own message on an error reply", async () => {
    const socket = new FakeSocket();
    const transport = createEngineAskTransport(socket);
    const pending = transport.request("ask.query", { query: "x" });
    socket.reply(socket.sent[0]!.id, "error", {
      code: "ask_error",
      message: "kill switch engaged: all external calls are halted",
    });
    await expect(pending).rejects.toThrow("kill switch engaged");
  });

  it("rejects an unexpected reply name instead of coercing it", async () => {
    const socket = new FakeSocket();
    const transport = createEngineAskTransport(socket);
    const pending = transport.request("ask.query", { query: "x" });
    socket.reply(socket.sent[0]!.id, "ok", {}); // not the pinned reply name
    await expect(pending).rejects.toThrow("engine replied ok");
  });

  it("times out honestly when the engine never answers", async () => {
    const socket = new FakeSocket();
    const transport = createEngineAskTransport(socket);
    const pending = transport.request("ask.query", { query: "x" });
    const assertion = expect(pending).rejects.toThrow("did not answer ask.query in time");
    vi.advanceTimersByTime(ASK_REPLY_TIMEOUT_MS + 1);
    await assertion;
  });

  it("refuses immediately when no socket is open (fail closed)", async () => {
    const socket = new FakeSocket();
    socket.online = false;
    const transport = createEngineAskTransport(socket);
    await expect(transport.request("ask.query", { query: "x" })).rejects.toThrow(
      "The engine is offline",
    );
  });

  it("a late duplicate reply after settlement changes nothing", async () => {
    const socket = new FakeSocket();
    const transport = createEngineAskTransport(socket);
    const pending = transport.request("ask.query", { query: "x" });
    const id = socket.sent[0]!.id;
    socket.reply(id, "ask.answer", { headline: "first" });
    await expect(pending).resolves.toEqual({ headline: "first" });
    // Replay defence: the listener already unsubscribed; nothing throws.
    socket.reply(id, "error", { message: "too late" });
  });
});
