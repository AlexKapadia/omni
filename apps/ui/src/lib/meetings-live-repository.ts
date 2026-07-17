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
  readonly segmentId: string;
  readonly stream: "me" | "them";
  readonly speakerLabel: string;
  readonly text: string;
  readonly tStart: number;
  readonly tEnd: number;
}

export interface MeetingExtractionData {
  readonly actions: readonly { readonly title: string; readonly owner?: string }[];
  readonly commitments: readonly { readonly who: string; readonly what: string }[];
  readonly openQuestions: readonly string[];
}

export interface MeetingDetail {
  readonly id: string;
  readonly title: string;
  readonly startIso: string;
  readonly endedIso: string | null;
  readonly durationMin: number;
  readonly finalized: boolean;
  readonly notePath: string | null;
  readonly notesText: string;
  readonly enhancedNotesMd: string;
  readonly extraction: MeetingExtractionData | null;
  /** True when me/them kept audio still exists for Retranscribe. */
  readonly hasKeptAudio: boolean;
  readonly transcript: readonly MeetingTranscriptLine[];
}

function mapTranscriptLine(value: unknown): MeetingTranscriptLine | null {
  if (typeof value !== "object" || value === null) return null;
  const line = value as Record<string, unknown>;
  const segmentId = asString(line["segment_id"]);
  const stream = line["stream"];
  const text = asString(line["text"]);
  const tStart = line["t_start"];
  const tEnd = line["t_end"];
  if (segmentId === null || segmentId.length === 0) return null;
  if ((stream !== "me" && stream !== "them") || text === null) return null;
  if (typeof tStart !== "number" || typeof tEnd !== "number") return null;
  if (!Number.isFinite(tStart) || !Number.isFinite(tEnd)) return null;
  const speakerLabelRaw = asString(line["speaker_label"]);
  const speakerLabel =
    speakerLabelRaw !== null && speakerLabelRaw.length > 0
      ? speakerLabelRaw
      : stream === "me"
        ? "Me"
        : "Them";
  return { segmentId, stream, speakerLabel, text, tStart, tEnd };
}

function mapExtraction(value: unknown): MeetingExtractionData | null {
  if (value === null || value === undefined) return null;
  if (typeof value !== "object") return null;
  const record = value as Record<string, unknown>;
  const actionsRaw = record["actions"];
  const commitmentsRaw = record["commitments"];
  const questionsRaw = record["open_questions"];
  if (!Array.isArray(actionsRaw) || !Array.isArray(commitmentsRaw)) return null;
  if (!Array.isArray(questionsRaw)) return null;
  // Local mutable copies — MeetingExtractionData fields are readonly arrays.
  const actions: { title: string; owner?: string }[] = [];
  for (const item of actionsRaw) {
    if (typeof item !== "object" || item === null) return null;
    const row = item as Record<string, unknown>;
    const title = asString(row["title"]);
    if (title === null) return null;
    const owner = asString(row["owner"]);
    actions.push(owner !== null ? { title, owner } : { title });
  }
  const commitments: { who: string; what: string }[] = [];
  for (const item of commitmentsRaw) {
    if (typeof item !== "object" || item === null) return null;
    const row = item as Record<string, unknown>;
    const who = asString(row["who"]);
    const what = asString(row["what"]);
    if (who === null || what === null) return null;
    commitments.push({ who, what });
  }
  const openQuestions: string[] = [];
  for (const q of questionsRaw) {
    if (typeof q !== "string") return null;
    openQuestions.push(q);
  }
  return { actions, commitments, openQuestions };
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
  const extraction = mapExtraction(payload["extraction"]);
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
  // Fail closed: omit/non-bool → no Retranscribe offer without proof of audio.
  const hasKeptAudio = payload["has_kept_audio"] === true;
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
    extraction,
    hasKeptAudio,
    transcript,
  };
}

export async function updateTranscriptSegment(
  meetingId: string,
  segmentId: string,
  text: string,
  transport: EngineRequestTransport = liveTransport,
): Promise<void> {
  await requestEngineReply(
    "transcript.segment.update",
    { meeting_id: meetingId, segment_id: segmentId, text },
    READ_TIMEOUT_MS,
    transport,
  );
}

export async function importMediaFile(
  path: string,
  title?: string,
  options?: { readonly identifySpeakers?: boolean },
  transport: EngineRequestTransport = liveTransport,
): Promise<string> {
  const payload = await requestEngineReply(
    "import.media",
    {
      path,
      title: title ?? null,
      identify_speakers: options?.identifySpeakers === true,
    },
    120_000,
    transport,
  );
  const meetingId = payload["meeting_id"];
  if (typeof meetingId !== "string" || meetingId.length === 0) {
    throw new Error("engine sent a malformed import reply");
  }
  return meetingId;
}

export async function retranscribeMeeting(
  meetingId: string,
  transport: EngineRequestTransport = liveTransport,
): Promise<void> {
  await requestEngineReply(
    "meeting.retranscribe",
    { meeting_id: meetingId },
    300_000,
    transport,
  );
}

export async function deleteMeeting(
  meetingId: string,
  transport: EngineRequestTransport = liveTransport,
): Promise<void> {
  const payload = await requestEngineReply(
    "meeting.delete",
    { meeting_id: meetingId },
    READ_TIMEOUT_MS,
    transport,
  );
  if (payload["deleted"] !== true) {
    throw new Error("engine sent a malformed delete reply");
  }
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
