/**
 * Transport tests: the generic ok-reply correlator resolves the matching reply
 * by envelope id, rejects on `error` with the engine's message, times out
 * honestly, and refuses immediately when the socket is closed (fail closed).
 * Plus: the model-download / google event subscriptions parse fail-closed.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import {
  ENGINE_SETUP_OFFLINE_MESSAGE,
  requestSetupCommand,
  subscribeToGoogleConnect,
  subscribeToModelsDownload,
  type EngineSocketTransport,
} from "./setup-settings-transport";
import { PROTOCOL_VERSION, type Envelope } from "./protocol";

function fakeSocket(sendOk = true) {
  let listener: ((data: unknown) => void) | null = null;
  const sent: Envelope[] = [];
  const transport: EngineSocketTransport = {
    sendEnvelope: (envelope) => {
      sent.push(envelope);
      return sendOk;
    },
    subscribeFrames: (l) => {
      listener = l;
      return () => {
        listener = null;
      };
    },
  };
  return {
    transport,
    sent,
    lastId: () => sent[sent.length - 1]?.id ?? "",
    emit: (frame: unknown) => listener?.(frame),
    hasListener: () => listener !== null,
  };
}

function reply(id: string, name: string, payload: Record<string, unknown>): Envelope {
  return { v: PROTOCOL_VERSION, kind: "reply", name, id, payload };
}

afterEach(() => vi.useRealTimers());

describe("requestSetupCommand correlation", () => {
  it("resolves the ok reply matched by id and ignores unrelated frames", async () => {
    const s = fakeSocket();
    const promise = requestSetupCommand("settings.get", {}, 1000, s.transport);
    // An unrelated reply (different id) must not settle the request.
    s.emit(reply("other-id", "ok", { nope: true }));
    s.emit(reply(s.lastId(), "ok", { settings: { a: 1 } }));
    await expect(promise).resolves.toEqual({ settings: { a: 1 } });
    expect(s.hasListener()).toBe(false); // unsubscribed on settle
  });

  it("rejects an error reply with the engine's own message", async () => {
    const s = fakeSocket();
    const promise = requestSetupCommand("settings.update", { values: {} }, 1000, s.transport);
    s.emit(reply(s.lastId(), "error", { code: "settings_error", message: "bad path" }));
    await expect(promise).rejects.toThrow("bad path");
  });

  it("fails closed immediately when the socket is not open", async () => {
    const s = fakeSocket(false); // sendEnvelope returns false
    await expect(requestSetupCommand("settings.get", {}, 1000, s.transport)).rejects.toThrow(
      ENGINE_SETUP_OFFLINE_MESSAGE,
    );
  });

  it("times out honestly when no reply arrives", async () => {
    vi.useFakeTimers();
    const s = fakeSocket();
    const promise = requestSetupCommand("ledger.summary", { limit: 20 }, 5000, s.transport);
    const assertion = expect(promise).rejects.toThrow(/did not answer/);
    await vi.advanceTimersByTimeAsync(5001);
    await assertion;
  });
});

describe("subscribeToModelsDownload", () => {
  it("routes progress / failed / completed to the right handlers, parsed", () => {
    const s = fakeSocket();
    const progress: unknown[] = [];
    const failed: unknown[] = [];
    const completed: unknown[] = [];
    subscribeToModelsDownload(
      {
        onProgress: (p) => progress.push(p),
        onFailed: (f) => failed.push(f),
        onCompleted: (c) => completed.push(c),
      },
      s.transport,
    );
    const evt = (name: string, payload: Record<string, unknown>) => ({
      v: PROTOCOL_VERSION,
      kind: "event",
      name,
      id: "e1",
      payload,
    });
    s.emit(evt("models.download.progress", { file: "m", received_bytes: 5, total_bytes: 10, sha256_verified: null }));
    s.emit(evt("models.download.progress", { file: "m", received_bytes: -1, total_bytes: 10, sha256_verified: null })); // corrupt: dropped
    s.emit(evt("models.download.failed", { file: "m", message: "boom" }));
    s.emit(evt("models.download.completed", { ok: true, files: ["m"] }));
    expect(progress).toHaveLength(1); // the corrupt frame was dropped
    expect(failed).toEqual([{ file: "m", message: "boom" }]);
    expect(completed).toEqual([{ ok: true, files: ["m"] }]);
  });
});

describe("subscribeToGoogleConnect", () => {
  it("delivers a parsed completion and ignores other events", () => {
    const s = fakeSocket();
    const results: unknown[] = [];
    subscribeToGoogleConnect((c) => results.push(c), s.transport);
    s.emit({ v: PROTOCOL_VERSION, kind: "event", name: "engine.heartbeat", id: "h", payload: {} });
    s.emit({ v: PROTOCOL_VERSION, kind: "event", name: "google.connect.completed", id: "g", payload: { ok: true, message: "Connected." } });
    expect(results).toEqual([{ ok: true, message: "Connected." }]);
  });
});
