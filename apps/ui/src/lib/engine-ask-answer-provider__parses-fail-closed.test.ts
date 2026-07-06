/**
 * Fail-closed parse tests for the REAL AskAnswerProvider: a pinned-shape
 * payload becomes an exact AskAnswer (headline, structured prose spans with
 * strong runs + citation markers, citations, latency); ANY shape deviation —
 * including a latency breakdown that does not add up — is refused; and with
 * no transport wired the provider rejects with the honest offline message.
 */
import { describe, expect, it } from "vitest";
import {
  ASK_QUERY_COMMAND_NAME,
  createEngineAskAnswerProvider,
  ENGINE_ASK_OFFLINE_MESSAGE,
  ENGINE_ASK_UNREADABLE_MESSAGE,
  parseAnswerProse,
  parseAskAnswerPayload,
  type AskQueryTransport,
} from "./engine-ask-answer-provider";

const GOOD_PAYLOAD = {
  headline: "March pricing",
  answer_md: "Held at **$18/seat**[1] through Q3, with a 12% volume discount [2].",
  no_answer: false,
  citations: [
    {
      n: 1,
      note_path: "meetings/2026-03-12-acme-pricing.md",
      line_start: 7,
      line_end: 9,
      heading_path: "Decisions",
      quote: "Hold the per-seat price at $18 through Q3.",
    },
    {
      n: 2,
      note_path: "notes/pricing-history.md",
      line_start: 3,
      line_end: 4,
      heading_path: "2026",
      quote: "12% discount above 500 seats.",
    },
  ],
  latency: { retrieval_ms: 12, synthesis_ms: 840, total_ms: 852 },
};

describe("parseAskAnswerPayload", () => {
  it("maps the pinned engine payload exactly", () => {
    const answer = parseAskAnswerPayload(GOOD_PAYLOAD);
    expect(answer).not.toBeNull();
    expect(answer!.headline).toBe("March pricing");
    expect(answer!.prose).toEqual([
      { text: "Held at " },
      { text: "$18/seat", strong: true, citationMarker: 1 },
      { text: " through Q3, with a 12% volume discount ", citationMarker: 2 },
      { text: "." },
    ]);
    expect(answer!.citations).toEqual([
      {
        marker: 1,
        notePath: "meetings/2026-03-12-acme-pricing.md",
        lineStart: 7,
        lineEnd: 9,
        headingPath: "Decisions",
        snippet: "Hold the per-seat price at $18 through Q3.",
      },
      {
        marker: 2,
        notePath: "notes/pricing-history.md",
        lineStart: 3,
        lineEnd: 4,
        headingPath: "2026",
        snippet: "12% discount above 500 seats.",
      },
    ]);
    expect(answer!.latency).toEqual({ retrievalMs: 12, synthesisMs: 840, totalMs: 852 });
  });

  it("refuses every shape deviation (fail closed, nothing coerced)", () => {
    const bad: unknown[] = [
      null,
      "a string",
      [],
      { ...GOOD_PAYLOAD, headline: "" },
      { ...GOOD_PAYLOAD, headline: 7 },
      { ...GOOD_PAYLOAD, answer_md: "" },
      { ...GOOD_PAYLOAD, no_answer: "false" },
      { ...GOOD_PAYLOAD, citations: "not an array" },
      // One malformed citation poisons the whole payload:
      { ...GOOD_PAYLOAD, citations: [{ n: 1 }] },
      { ...GOOD_PAYLOAD, citations: [{ ...GOOD_PAYLOAD.citations[0], n: 0 }] },
      { ...GOOD_PAYLOAD, citations: [{ ...GOOD_PAYLOAD.citations[0], line_start: 0 }] },
      // line_end < line_start is a corrupt citation target:
      { ...GOOD_PAYLOAD, citations: [{ ...GOOD_PAYLOAD.citations[0], line_end: 6 }] },
      { ...GOOD_PAYLOAD, citations: [{ ...GOOD_PAYLOAD.citations[0], line_start: 1.5 }] },
      { ...GOOD_PAYLOAD, latency: undefined },
      { ...GOOD_PAYLOAD, latency: { retrieval_ms: 12, synthesis_ms: 840 } },
      { ...GOOD_PAYLOAD, latency: { retrieval_ms: -1, synthesis_ms: 0, total_ms: -1 } },
      // Latency arithmetic must be exact to the unit — 851 !== 12 + 840:
      { ...GOOD_PAYLOAD, latency: { retrieval_ms: 12, synthesis_ms: 840, total_ms: 851 } },
    ];
    for (const payload of bad) {
      expect(parseAskAnswerPayload(payload), JSON.stringify(payload)).toBeNull();
    }
  });
});

describe("parseAnswerProse", () => {
  it("attaches markers to the preceding span and drops unknown markers", () => {
    const spans = parseAnswerProse("A fact [1] and **bold**[2] and ghost [9].", new Set([1, 2]));
    expect(spans).toEqual([
      { text: "A fact ", citationMarker: 1 },
      { text: " and " },
      { text: "bold", strong: true, citationMarker: 2 },
      { text: " and ghost " }, // [9] has no citation: no dangling sup rendered
      { text: "." },
    ]);
  });

  it("handles a leading marker with no preceding span", () => {
    expect(parseAnswerProse("[1] leads", new Set([1]))).toEqual([
      { text: "", citationMarker: 1 },
      { text: " leads" },
    ]);
  });
});

describe("createEngineAskAnswerProvider", () => {
  it("rejects honestly when no transport is wired (fail closed)", async () => {
    const provider = createEngineAskAnswerProvider();
    await expect(provider.answer("anything")).rejects.toThrow(ENGINE_ASK_OFFLINE_MESSAGE);
  });

  it("sends the pinned ask.query command and returns the parsed answer", async () => {
    const requests: Array<{ name: string; payload: Record<string, unknown> }> = [];
    const transport: AskQueryTransport = {
      request: (name, payload) => {
        requests.push({ name, payload });
        return Promise.resolve(GOOD_PAYLOAD as unknown as Record<string, unknown>);
      },
    };
    const provider = createEngineAskAnswerProvider(transport);
    const answer = await provider.answer("what did we agree on pricing in March?");
    expect(requests).toEqual([
      {
        name: ASK_QUERY_COMMAND_NAME,
        payload: { query: "what did we agree on pricing in March?" },
      },
    ]);
    expect(answer.headline).toBe("March pricing");
  });

  it("rejects an unreadable reply instead of rendering it (fail closed)", async () => {
    const transport: AskQueryTransport = {
      request: () => Promise.resolve({ garbage: true }),
    };
    const provider = createEngineAskAnswerProvider(transport);
    await expect(provider.answer("q")).rejects.toThrow(ENGINE_ASK_UNREADABLE_MESSAGE);
  });
});
