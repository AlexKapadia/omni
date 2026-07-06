/**
 * LIVE MeetingsRepository — the real M2 engine data source over the WS
 * protocol (meetings.list / meeting.get / meeting.finalize), replacing the
 * M0 mock. Correlates replies to commands by envelope id, times out
 * honestly, and validates every payload fail-closed: a malformed row is a
 * surfaced error, never a silently-coerced list.
 *
 * Security invariant: every inbound frame is untrusted — it goes through
 * parseInboundMessage plus per-field type checks before any value reaches a
 * store or the screen.
 */
import { sendEngineEnvelope, subscribeToEngineFrames } from "./live-engine-socket";
import type { MeetingsRepository, MeetingSummaryRow } from "./meetings-store";
import { makeCommand, parseInboundMessage, type Envelope } from "./protocol";

/** Injectable transport so unit tests drive the correlation with fakes. */
export interface EngineRequestTransport {
  sendEnvelope(envelope: Envelope): boolean;
  subscribeFrames(listener: (data: unknown) => void): () => void;
}

const liveTransport: EngineRequestTransport = {
  sendEnvelope: sendEngineEnvelope,
  subscribeFrames: subscribeToEngineFrames,
};

export const ENGINE_OFFLINE_MESSAGE =
  "The engine is offline. The library needs the engine running on this device.";

/** Reads are quick; finalize runs multiple model calls and may take a while. */
const READ_TIMEOUT_MS = 10_000;
const FINALIZE_TIMEOUT_MS = 120_000;

/**
 * Send one command and await its correlated reply payload.
 * Resolves on an `ok` reply with the command's id; rejects on an `error`
 * reply (with the engine's plain-voice message), on timeout, and
 * immediately when no socket is open (fail closed, honest).
 */
export function requestEngineReply(
  name: string,
  payload: Record<string, unknown>,
  timeoutMs: number,
  transport: EngineRequestTransport = liveTransport,
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
    const unsubscribe = transport.subscribeFrames((data) => {
      const parsed = parseInboundMessage(data);
      // Unrelated frames (heartbeats, events, other replies) pass through.
      if (!parsed.ok || parsed.envelope.kind !== "reply") return;
      if (parsed.envelope.id !== envelope.id) return;
      const reply = parsed.envelope;
      if (reply.name === "ok") {
        finish(() => resolve(reply.payload));
        return;
      }
      // Any non-ok reply is a refusal — surface the engine's own message.
      const message = reply.payload["message"];
      finish(() =>
        reject(new Error(typeof message === "string" ? message : `engine replied ${reply.name}`)),
      );
    });
    const timer = setTimeout(() => {
      finish(() => reject(new Error(`the engine did not answer ${name} in time`)));
    }, timeoutMs);
    if (!transport.sendEnvelope(envelope)) {
      finish(() => reject(new Error(ENGINE_OFFLINE_MESSAGE)));
    }
  });
}

// ---------------------------------------------------------------- mapping
function asString(value: unknown): string | null {
  return typeof value === "string" ? value : null;
}

function mapSummaryRow(value: unknown): MeetingSummaryRow | null {
  if (typeof value !== "object" || value === null) return null;
  const row = value as Record<string, unknown>;
  const id = asString(row["id"]);
  const title = asString(row["title"]);
  const summary = asString(row["summary"]);
  const startIso = asString(row["start_iso"]);
  const durationMin = row["duration_min"];
  if (id === null || id.length === 0 || title === null || summary === null) return null;
  if (startIso === null || typeof durationMin !== "number" || !Number.isFinite(durationMin)) {
    return null;
  }
  return { id, title, summary, startIso, durationMin };
}

export interface MeetingTranscriptLine {
  readonly stream: "me" | "them";
  readonly text: string;
}

export interface MeetingDetail {
  readonly id: string;
  readonly title: string;
  readonly startIso: string;
  readonly endedIso: string | null;
  readonly durationMin: number;
  readonly finalized: boolean;
  readonly notePath: string | null;
  /** The user's rough notes, verbatim (fidelity mandate). */
  readonly notesText: string;
  /** Sanitised enhancement markdown; empty until enhanced. */
  readonly enhancedNotesMd: string;
  readonly transcript: readonly MeetingTranscriptLine[];
}

function mapTranscriptLine(value: unknown): MeetingTranscriptLine | null {
  if (typeof value !== "object" || value === null) return null;
  const line = value as Record<string, unknown>;
  const stream = line["stream"];
  const text = asString(line["text"]);
  if ((stream !== "me" && stream !== "them") || text === null) return null;
  return { stream, text };
}

function mapDetail(payload: Record<string, unknown>): MeetingDetail | null {
  const id = asString(payload["id"]);
  const title = asString(payload["title"]);
  const startIso = asString(payload["start_iso"]);
  const endedIso = payload["ended_iso"] === null ? null : asString(payload["ended_iso"]);
  const durationMin = payload["duration_min"];
  const finalized = payload["finalized"];
  const notePath = payload["note_path"] === null ? null : asString(payload["note_path"]);
  const notesText = asString(payload["notes_text"]);
  const enhancedNotesMd = asString(payload["enhanced_notes_md"]);
  const transcriptRaw = payload["transcript"];
  if (id === null || title === null || startIso === null || notesText === null) return null;
  if (typeof durationMin !== "number" || !Number.isFinite(durationMin)) return null;
  if (typeof finalized !== "boolean" || enhancedNotesMd === null) return null;
  if (!Array.isArray(transcriptRaw)) return null;
  const transcript: MeetingTranscriptLine[] = [];
  for (const item of transcriptRaw) {
    const line = mapTranscriptLine(item);
    if (line === null) return null; // fail closed: one bad line rejects the frame
    transcript.push(line);
  }
  return {
    id,
    title,
    startIso,
    endedIso,
    durationMin,
    finalized,
    notePath,
    notesText,
    enhancedNotesMd,
    transcript,
  };
}

// ------------------------------------------------------------- public API
export function createLiveMeetingsRepository(
  transport: EngineRequestTransport = liveTransport,
): MeetingsRepository {
  return {
    listMeetings: async () => {
      const payload = await requestEngineReply("meetings.list", {}, READ_TIMEOUT_MS, transport);
      const meetings = payload["meetings"];
      if (!Array.isArray(meetings)) throw new Error("engine sent a malformed meeting list");
      return meetings.map((value) => {
        const row = mapSummaryRow(value);
        if (row === null) throw new Error("engine sent a malformed meeting row");
        return row;
      });
    },
  };
}

export async function getMeetingDetail(
  meetingId: string,
  transport: EngineRequestTransport = liveTransport,
): Promise<MeetingDetail> {
  const payload = await requestEngineReply(
    "meeting.get",
    { meeting_id: meetingId },
    READ_TIMEOUT_MS,
    transport,
  );
  const detail = mapDetail(payload);
  if (detail === null) throw new Error("engine sent a malformed meeting detail");
  return detail;
}

export interface FinalizeOutcome {
  readonly notePath: string;
  readonly enhanceOk: boolean;
  readonly extractionOk: boolean;
  readonly warnings: readonly string[];
}

export async function requestMeetingFinalize(
  meetingId: string,
  notepadText: string,
  template: string | null = null,
  transport: EngineRequestTransport = liveTransport,
): Promise<FinalizeOutcome> {
  const commandPayload: Record<string, unknown> = {
    meeting_id: meetingId,
    notepad_text: notepadText, // verbatim — the engine stores the exact bytes
  };
  if (template !== null) commandPayload["template"] = template;
  const payload = await requestEngineReply(
    "meeting.finalize",
    commandPayload,
    FINALIZE_TIMEOUT_MS,
    transport,
  );
  const notePath = asString(payload["note_path"]);
  const enhanceOk = payload["enhance_ok"];
  const extractionOk = payload["extraction_ok"];
  const warningsRaw = payload["warnings"];
  if (notePath === null || typeof enhanceOk !== "boolean" || typeof extractionOk !== "boolean") {
    throw new Error("engine sent a malformed finalize reply");
  }
  const warnings = Array.isArray(warningsRaw)
    ? warningsRaw.filter((w): w is string => typeof w === "string")
    : [];
  return { notePath, enhanceOk, extractionOk, warnings };
}
