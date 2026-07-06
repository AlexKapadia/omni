/**
 * REAL AskAnswerProvider over the engine's `ask.query` command.
 *
 * The engine's M3 pipeline (engine/ask/ask_omni_answer_service.py) replies
 * `ask.answer` with `{headline, answer_md, no_answer, citations[], latency}`;
 * this provider parses that payload FAIL-CLOSED into the UI's AskAnswer shape,
 * turning inline [n] markers and **bold** runs in answer_md into structured
 * prose spans — never raw model text into the DOM.
 *
 * WIRING (DEFERRED — orchestrator connects at reconciliation): the WS layer
 * calls setAskQueryTransport() with a request/reply implementation that sends
 * a `ask.query` command envelope and resolves the correlated `ask.answer`
 * reply payload. Until wired, answer() rejects with the honest offline
 * message — the Ask screen's error state renders it (fail closed, no fake
 * answers, nothing static).
 *
 * Security invariants:
 * - Fail-closed parse: ANY deviation from the pinned payload shape rejects;
 *   nothing is coerced or partially accepted.
 * - Latency exactness gate: total_ms must equal retrieval_ms + synthesis_ms
 *   to the unit (zero-numerical-errors rule) or the payload is refused.
 */
import type {
  AskAnswer,
  AskAnswerProvider,
  AskCitation,
  AskLatencyBreakdown,
  AskProseSpan,
} from "./ask-store";

/** Command/reply names pinned with the engine (engine/ask/__init__.py). */
export const ASK_QUERY_COMMAND_NAME = "ask.query";
export const ASK_ANSWER_REPLY_NAME = "ask.answer";

export const ENGINE_ASK_OFFLINE_MESSAGE =
  "The engine is offline. Ask needs the engine running on this device.";
export const ENGINE_ASK_UNREADABLE_MESSAGE =
  "The engine returned an answer the app could not read.";

/** The request/reply seam the WS wiring provides at reconciliation. */
export interface AskQueryTransport {
  request(name: string, payload: Record<string, unknown>): Promise<Record<string, unknown>>;
}

let wiredTransport: AskQueryTransport | null = null;

/** Called by the WS wiring once the engine socket can correlate replies. */
export function setAskQueryTransport(transport: AskQueryTransport | null): void {
  wiredTransport = transport;
}

function isPlainObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isCount(value: unknown): value is number {
  return typeof value === "number" && Number.isInteger(value) && value >= 0;
}

function parseCitation(value: unknown): AskCitation | null {
  if (!isPlainObject(value)) return null;
  const { n, note_path, line_start, line_end, heading_path, quote } = value;
  if (!isCount(n) || n < 1) return null;
  if (typeof note_path !== "string" || note_path.length === 0) return null;
  if (!isCount(line_start) || line_start < 1) return null;
  if (!isCount(line_end) || line_end < line_start) return null;
  if (typeof heading_path !== "string" || typeof quote !== "string") return null;
  return {
    marker: n,
    notePath: note_path,
    lineStart: line_start,
    lineEnd: line_end,
    headingPath: heading_path,
    snippet: quote,
  };
}

function parseLatency(value: unknown): AskLatencyBreakdown | null {
  if (!isPlainObject(value)) return null;
  const { retrieval_ms, synthesis_ms, total_ms } = value;
  if (!isCount(retrieval_ms) || !isCount(synthesis_ms) || !isCount(total_ms)) return null;
  // Exactness gate: the breakdown must add up to the unit, or it is refused.
  if (total_ms !== retrieval_ms + synthesis_ms) return null;
  return { retrievalMs: retrieval_ms, synthesisMs: synthesis_ms, totalMs: total_ms };
}

/** Tokenises answer_md into spans: plain text, **bold** runs, [n] markers. */
const PROSE_TOKEN = /(\*\*[^*]+\*\*|\[\d+\])/g;

export function parseAnswerProse(
  answerMd: string,
  validMarkers: ReadonlySet<number>,
): AskProseSpan[] {
  const spans: AskProseSpan[] = [];
  for (const token of answerMd.split(PROSE_TOKEN)) {
    if (token.length === 0) continue;
    const markerMatch = /^\[(\d+)\]$/.exec(token);
    if (markerMatch !== null) {
      const marker = Number(markerMatch[1]);
      if (!validMarkers.has(marker)) continue; // no chip -> no dangling sup
      const previous = spans[spans.length - 1];
      if (previous !== undefined && previous.citationMarker === undefined) {
        spans[spans.length - 1] = { ...previous, citationMarker: marker };
      } else {
        spans.push({ text: "", citationMarker: marker });
      }
      continue;
    }
    if (token.startsWith("**") && token.endsWith("**")) {
      spans.push({ text: token.slice(2, -2), strong: true });
      continue;
    }
    spans.push({ text: token });
  }
  return spans;
}

/**
 * Validate one `ask.answer` payload against the pinned engine contract.
 * Returns null on ANY deviation — the caller surfaces an honest error.
 */
export function parseAskAnswerPayload(payload: unknown): AskAnswer | null {
  if (!isPlainObject(payload)) return null;
  const { headline, answer_md, no_answer, citations } = payload;
  if (typeof headline !== "string" || headline.length === 0) return null;
  if (typeof answer_md !== "string" || answer_md.length === 0) return null;
  if (typeof no_answer !== "boolean") return null;
  if (!Array.isArray(citations)) return null;
  const parsedCitations: AskCitation[] = [];
  for (const raw of citations) {
    const citation = parseCitation(raw);
    if (citation === null) return null; // one bad citation poisons the payload
    parsedCitations.push(citation);
  }
  const latency = parseLatency(payload["latency"]);
  if (latency === null) return null;
  const validMarkers = new Set(parsedCitations.map((c) => c.marker));
  return {
    headline,
    prose: parseAnswerProse(answer_md, validMarkers),
    citations: parsedCitations,
    latency,
  };
}

/**
 * Build the real provider. Pass a transport explicitly (tests), or rely on
 * the module-level transport the WS wiring registers. No transport = an
 * honest rejection, which the Ask screen renders as its error state.
 */
export function createEngineAskAnswerProvider(transport?: AskQueryTransport): AskAnswerProvider {
  return {
    answer: async (question: string): Promise<AskAnswer> => {
      const active = transport ?? wiredTransport;
      if (active === null || active === undefined) {
        throw new Error(ENGINE_ASK_OFFLINE_MESSAGE); // fail closed, honestly
      }
      const payload = await active.request(ASK_QUERY_COMMAND_NAME, { query: question });
      const parsed = parseAskAnswerPayload(payload);
      if (parsed === null) {
        throw new Error(ENGINE_ASK_UNREADABLE_MESSAGE); // fail closed on shape
      }
      return parsed;
    },
  };
}
