/**
 * Adversarial tests for the fail-closed protocol v1 validator.
 *
 * Every case here is a frame a buggy/hostile peer could send; the validator
 * must reject each with ok:false and must never partially accept or coerce.
 */
import { describe, expect, it } from "vitest";
import {
  parseHeartbeatPayload,
  parseInboundMessage,
  PROTOCOL_VERSION,
} from "./protocol";

function validEvent(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    v: 1,
    kind: "event",
    name: "engine.heartbeat",
    id: "abc-123",
    payload: { uptime_s: 5, engine_version: "0.1.0", python: "3.12.4", stt_ready: false },
    ...overrides,
  };
}

describe("parseInboundMessage rejects malformed envelopes", () => {
  it.each<[string, unknown]>([
    ["invalid JSON text", "{nope"],
    ["bare word (invalid JSON)", "hi"],
    ["JSON string root", '"hello"'],
    ["JSON number root", "42"],
    ["JSON array root", '[{"v":1}]'],
    ["JSON null root", "null"],
    ["JSON true root", "true"],
    ["empty JSON object", "{}"],
    ["raw number", 42],
    ["raw null", null],
    ["raw undefined", undefined],
    ["raw array", [validEvent()]],
    ["class instance root", new Date()],
  ])("rejects %s", (_label, raw) => {
    expect(parseInboundMessage(raw).ok).toBe(false);
  });

  it.each<[string, unknown]>([
    ["v is 0", 0],
    ["v is 2 (future version)", 2],
    ["v is the string '1'", "1"],
    ["v is 1.5", 1.5],
    ["v is null", null],
    ["v is missing", undefined],
  ])("rejects wrong version: %s", (_label, v) => {
    const frame = validEvent();
    if (v === undefined) delete frame["v"];
    else frame["v"] = v;
    expect(parseInboundMessage(frame).ok).toBe(false);
  });

  it.each<[string, unknown]>([
    ["kind 'command' (outbound-only, must not be accepted inbound)", "command"],
    ["kind 'EVENT' (case matters)", "EVENT"],
    ["kind 'events' (near miss)", "events"],
    ["kind empty string", ""],
    ["kind null", null],
    ["kind numeric", 3],
    ["kind missing", undefined],
  ])("rejects bad kind: %s", (_label, kind) => {
    const frame = validEvent();
    if (kind === undefined) delete frame["kind"];
    else frame["kind"] = kind;
    expect(parseInboundMessage(frame).ok).toBe(false);
  });

  it.each<[string, unknown]>([
    ["id missing", undefined],
    ["id empty string", ""],
    ["id numeric", 7],
    ["id null", null],
    ["id object", {}],
  ])("rejects bad id: %s", (_label, id) => {
    const frame = validEvent();
    if (id === undefined) delete frame["id"];
    else frame["id"] = id;
    expect(parseInboundMessage(frame).ok).toBe(false);
  });

  it.each<[string, unknown]>([
    ["name missing", undefined],
    ["name empty string", ""],
    ["name numeric", 42],
    ["name null", null],
  ])("rejects bad name: %s", (_label, name) => {
    const frame = validEvent();
    if (name === undefined) delete frame["name"];
    else frame["name"] = name;
    expect(parseInboundMessage(frame).ok).toBe(false);
  });

  it.each<[string, unknown]>([
    ["payload missing", undefined],
    ["payload null", null],
    ["payload array", [1, 2]],
    ["payload string", "x"],
    ["payload number", 3],
    ["payload class instance", new Date()],
  ])("rejects bad payload: %s", (_label, payload) => {
    const frame = validEvent();
    if (payload === undefined) delete frame["payload"];
    else frame["payload"] = payload;
    expect(parseInboundMessage(frame).ok).toBe(false);
  });

  it("accepts a valid event and preserves its fields exactly", () => {
    const result = parseInboundMessage(JSON.stringify(validEvent()));
    expect(result.ok).toBe(true);
    if (!result.ok) return;
    expect(result.envelope.v).toBe(PROTOCOL_VERSION);
    expect(result.envelope.kind).toBe("event");
    expect(result.envelope.name).toBe("engine.heartbeat");
    expect(result.envelope.id).toBe("abc-123");
    expect(result.envelope.payload["uptime_s"]).toBe(5);
  });

  it("accepts a valid reply", () => {
    const result = parseInboundMessage({ v: 1, kind: "reply", name: "pong", id: "x1", payload: {} });
    expect(result.ok).toBe(true);
  });

  it("gives a reason for every rejection (fail closed, but diagnosable)", () => {
    const result = parseInboundMessage("{broken");
    expect(result.ok).toBe(false);
    if (result.ok) return;
    expect(result.reason.length).toBeGreaterThan(0);
  });
});

describe("parseHeartbeatPayload rejects corrupt heartbeats", () => {
  const valid = { uptime_s: 12.5, engine_version: "0.1.0", python: "3.12.4", stt_ready: true };

  it("accepts a valid heartbeat", () => {
    expect(parseHeartbeatPayload(valid)).toEqual(valid);
  });

  it("accepts uptime_s of exactly 0 (boundary)", () => {
    expect(parseHeartbeatPayload({ ...valid, uptime_s: 0 })).not.toBeNull();
  });

  it.each<[string, Record<string, unknown>]>([
    ["uptime_s as string", { ...valid, uptime_s: "5" }],
    ["uptime_s negative", { ...valid, uptime_s: -0.001 }],
    ["uptime_s NaN", { ...valid, uptime_s: Number.NaN }],
    ["uptime_s Infinity", { ...valid, uptime_s: Number.POSITIVE_INFINITY }],
    ["uptime_s missing", { engine_version: "0.1.0", python: "3.12.4", stt_ready: true }],
    ["engine_version empty", { ...valid, engine_version: "" }],
    ["engine_version numeric", { ...valid, engine_version: 3 }],
    ["python missing", { uptime_s: 1, engine_version: "0.1.0", stt_ready: true }],
    ["stt_ready as string 'true'", { ...valid, stt_ready: "true" }],
    ["stt_ready as 1", { ...valid, stt_ready: 1 }],
    ["stt_ready null", { ...valid, stt_ready: null }],
  ])("rejects %s", (_label, payload) => {
    expect(parseHeartbeatPayload(payload)).toBeNull();
  });
});
