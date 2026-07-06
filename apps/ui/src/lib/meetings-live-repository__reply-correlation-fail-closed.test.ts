/**
 * Live meetings repository: reply correlation by envelope id, honest
 * timeouts/offline refusals, and fail-closed payload validation — a
 * malformed engine frame surfaces as an error, never as coerced data.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import {
  createLiveMeetingsRepository,
  ENGINE_OFFLINE_MESSAGE,
  getMeetingDetail,
  requestEngineReply,
  requestMeetingFinalize,
  type EngineRequestTransport,
} from "./meetings-live-repository";
import type { Envelope } from "./protocol";

class FakeTransport implements EngineRequestTransport {
  readonly sent: Envelope[] = [];
  online = true;
  private readonly listeners = new Set<(data: unknown) => void>();

  sendEnvelope(envelope: Envelope): boolean {
    if (!this.online) return false;
    this.sent.push(envelope);
    return true;
  }

  subscribeFrames(listener: (data: unknown) => void): () => void {
    this.listeners.add(listener);
    return () => {
      this.listeners.delete(listener);
    };
  }

  emit(frame: Record<string, unknown>): void {
    for (const listener of [...this.listeners]) listener(JSON.stringify(frame));
  }

  get listenerCount(): number {
    return this.listeners.size;
  }
}

function reply(id: string, name: "ok" | "error", payload: Record<string, unknown>) {
  return { v: 1, kind: "reply", name, id, payload };
}

const VALID_ROW = {
  id: "m-1",
  title: "Vendor sync",
  summary: "Renewal agreed.",
  start_iso: "2026-07-06T10:00:00+00:00",
  duration_min: 30,
};

const VALID_DETAIL = {
  id: "m-1",
  title: "Vendor sync",
  start_iso: "2026-07-06T10:00:00+00:00",
  ended_iso: "2026-07-06T10:30:00+00:00",
  duration_min: 30,
  finalized: true,
  note_path: "Meetings/2026-07-06 Vendor sync.md",
  notes_text: "raw notes\nwith a second line",
  enhanced_notes_md: "## Summary\nDone.",
  transcript: [
    { stream: "them", text: "hello" },
    { stream: "me", text: "hi" },
  ],
};

afterEach(() => {
  vi.useRealTimers();
});

describe("requestEngineReply correlation", () => {
  it("resolves the ok reply that matches the command id, ignoring noise", async () => {
    const transport = new FakeTransport();
    const promise = requestEngineReply("meetings.list", {}, 1000, transport);
    const commandId = transport.sent[0]!.id;
    // Noise first: a heartbeat event and an unrelated reply must be ignored.
    transport.emit({ v: 1, kind: "event", name: "engine.heartbeat", id: "hb", payload: {} });
    transport.emit(reply("some-other-command", "ok", { wrong: true }));
    transport.emit(reply(commandId, "ok", { meetings: [] }));
    await expect(promise).resolves.toEqual({ meetings: [] });
    expect(transport.listenerCount).toBe(0); // subscription released
  });

  it("rejects with the engine's own message on an error reply", async () => {
    const transport = new FakeTransport();
    const promise = requestEngineReply("meeting.finalize", { meeting_id: "x" }, 1000, transport);
    transport.emit(
      reply(transport.sent[0]!.id, "error", {
        code: "finalize_error",
        message: "meeting is already finalized",
      }),
    );
    await expect(promise).rejects.toThrow("meeting is already finalized");
  });

  it("rejects immediately when the engine is offline, sending nothing", async () => {
    const transport = new FakeTransport();
    transport.online = false;
    await expect(requestEngineReply("meetings.list", {}, 1000, transport)).rejects.toThrow(
      ENGINE_OFFLINE_MESSAGE,
    );
    expect(transport.sent).toEqual([]);
    expect(transport.listenerCount).toBe(0);
  });

  it("rejects on timeout and releases the subscription", async () => {
    vi.useFakeTimers();
    const transport = new FakeTransport();
    const promise = requestEngineReply("meetings.list", {}, 5000, transport);
    const expectation = expect(promise).rejects.toThrow("did not answer meetings.list in time");
    vi.advanceTimersByTime(5001);
    await expectation;
    expect(transport.listenerCount).toBe(0);
  });

  it("a late reply after settling is ignored (no double settle, no throw)", async () => {
    const transport = new FakeTransport();
    const promise = requestEngineReply("meetings.list", {}, 1000, transport);
    const commandId = transport.sent[0]!.id;
    transport.emit(reply(commandId, "ok", { meetings: [] }));
    await promise;
    transport.emit(reply(commandId, "error", { message: "too late" })); // must be inert
  });
});

describe("meetings.list mapping (fail closed)", () => {
  async function listWith(payload: Record<string, unknown>) {
    const transport = new FakeTransport();
    const repository = createLiveMeetingsRepository(transport);
    const promise = repository.listMeetings();
    transport.emit(reply(transport.sent[0]!.id, "ok", payload));
    return promise;
  }

  it("maps valid snake_case rows to the store's camelCase shape", async () => {
    const rows = await listWith({ meetings: [VALID_ROW] });
    expect(rows).toEqual([
      {
        id: "m-1",
        title: "Vendor sync",
        summary: "Renewal agreed.",
        startIso: "2026-07-06T10:00:00+00:00",
        durationMin: 30,
      },
    ]);
  });

  it.each([
    [{ meetings: "not-a-list" }],
    [{ meetings: [{ ...VALID_ROW, id: 42 }] }],
    [{ meetings: [{ ...VALID_ROW, duration_min: "30" }] }],
    [{ meetings: [{ ...VALID_ROW, duration_min: Number.NaN }] }],
    [{ meetings: [{ title: "missing everything else" }] }],
    [{}],
  ])("rejects malformed list payloads instead of coercing: %j", async (payload) => {
    await expect(listWith(payload as Record<string, unknown>)).rejects.toThrow(/malformed/);
  });
});

describe("meeting.get mapping (fail closed)", () => {
  async function getWith(payload: Record<string, unknown>) {
    const transport = new FakeTransport();
    const promise = getMeetingDetail("m-1", transport);
    expect(transport.sent[0]!.payload).toEqual({ meeting_id: "m-1" });
    transport.emit(reply(transport.sent[0]!.id, "ok", payload));
    return promise;
  }

  it("maps the full detail payload, transcript order preserved", async () => {
    const detail = await getWith(VALID_DETAIL);
    expect(detail.notesText).toBe("raw notes\nwith a second line"); // verbatim
    expect(detail.finalized).toBe(true);
    expect(detail.transcript).toEqual([
      { stream: "them", text: "hello" },
      { stream: "me", text: "hi" },
    ]);
  });

  it.each([
    [{ ...VALID_DETAIL, transcript: [{ stream: "attacker", text: "x" }] }],
    [{ ...VALID_DETAIL, transcript: "not-a-list" }],
    [{ ...VALID_DETAIL, finalized: "yes" }],
    [{ ...VALID_DETAIL, notes_text: null }],
  ])("rejects malformed detail payloads: %j", async (payload) => {
    await expect(getWith(payload as Record<string, unknown>)).rejects.toThrow(/malformed/);
  });
});

describe("meeting.finalize command + mapping", () => {
  it("sends the notepad verbatim and maps the outcome", async () => {
    const transport = new FakeTransport();
    const notepad = "line one\r\n  spaced line — kept exactly\n";
    const promise = requestMeetingFinalize("m-1", notepad, "sales", transport);
    const sent = transport.sent[0]!;
    expect(sent.name).toBe("meeting.finalize");
    expect(sent.payload).toEqual({
      meeting_id: "m-1",
      notepad_text: notepad, // byte-identical on the wire
      template: "sales",
    });
    transport.emit(
      reply(sent.id, "ok", {
        meeting_id: "m-1",
        note_path: "Meetings/x.md",
        template_id: "sales",
        enhance_ok: true,
        extraction_ok: false,
        indexed_chunks: 2,
        warnings: ["extraction unavailable: model JSON failed validation twice"],
      }),
    );
    await expect(promise).resolves.toEqual({
      notePath: "Meetings/x.md",
      enhanceOk: true,
      extractionOk: false,
      warnings: ["extraction unavailable: model JSON failed validation twice"],
    });
  });

  it("omits the template field entirely when not chosen (engine's auto default)", async () => {
    const transport = new FakeTransport();
    void requestMeetingFinalize("m-1", "", null, transport).catch(() => undefined);
    expect(transport.sent[0]!.payload).toEqual({ meeting_id: "m-1", notepad_text: "" });
  });
});
