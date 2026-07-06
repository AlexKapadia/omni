/**
 * Live-answers store: answers.hit event handling — fail-closed parse,
 * duplicate/out-of-order idempotence, newest-first ordering, the cap, and
 * the meeting-boundary clear.
 */
import { describe, expect, it } from "vitest";
import {
  applyAnswersHit,
  clearLiveAnswers,
  createLiveAnswersStore,
  MAX_LIVE_ANSWER_HITS,
  parseAnswersHitPayload,
} from "./live-answers-store";

const GOOD_HIT = {
  question: "What did we agree on pricing in March?",
  asked_by: "them",
  spotted_to_hit_ms: 740,
  hits: [
    {
      note_path: "meetings/2026-03-12-acme-pricing.md",
      line_start: 7,
      line_end: 9,
      heading_path: "Decisions",
      snippet: "Hold the per-seat price at $18 through Q3.",
      score: 0.031,
    },
  ],
};

describe("parseAnswersHitPayload", () => {
  it("maps the pinned engine payload exactly", () => {
    const hit = parseAnswersHitPayload(GOOD_HIT);
    expect(hit).toEqual({
      id: "what did we agree on pricing in march",
      question: "What did we agree on pricing in March?",
      askedBy: "them",
      spottedToHitMs: 740,
      sources: [
        {
          notePath: "meetings/2026-03-12-acme-pricing.md",
          lineStart: 7,
          lineEnd: 9,
          headingPath: "Decisions",
          snippet: "Hold the per-seat price at $18 through Q3.",
          score: 0.031,
        },
      ],
    });
  });

  it("refuses every shape deviation, including empty hits (fail closed)", () => {
    const bad: unknown[] = [
      null,
      [],
      { ...GOOD_HIT, question: "  " },
      { ...GOOD_HIT, asked_by: 3 },
      { ...GOOD_HIT, spotted_to_hit_ms: -1 },
      { ...GOOD_HIT, spotted_to_hit_ms: 1.5 },
      { ...GOOD_HIT, hits: [] }, // the engine never emits an empty hit
      { ...GOOD_HIT, hits: "nope" },
      { ...GOOD_HIT, hits: [{ ...GOOD_HIT.hits[0], score: Number.NaN }] },
      { ...GOOD_HIT, hits: [{ ...GOOD_HIT.hits[0], line_end: 6 }] }, // end < start
      { ...GOOD_HIT, hits: [GOOD_HIT.hits[0], { note_path: "x.md" }] }, // one bad source
    ];
    for (const payload of bad) {
      expect(parseAnswersHitPayload(payload), JSON.stringify(payload)).toBeNull();
    }
  });
});

describe("applyAnswersHit", () => {
  it("a malformed frame never mutates the store", () => {
    const store = createLiveAnswersStore();
    applyAnswersHit(store, { junk: true });
    expect(store.getState().hits).toEqual([]);
  });

  it("duplicate and out-of-order replays are idempotent by question identity", () => {
    const store = createLiveAnswersStore();
    applyAnswersHit(store, GOOD_HIT);
    // Same question replayed with different punctuation/case: still one hit.
    applyAnswersHit(store, { ...GOOD_HIT, question: "what did we agree on pricing in MARCH??" });
    applyAnswersHit(store, GOOD_HIT);
    expect(store.getState().hits).toHaveLength(1);
  });

  it("new hits prepend (newest first) and the list caps", () => {
    const store = createLiveAnswersStore();
    for (let i = 0; i < MAX_LIVE_ANSWER_HITS + 5; i += 1) {
      applyAnswersHit(store, { ...GOOD_HIT, question: `Question number ${i}?` });
    }
    const hits = store.getState().hits;
    expect(hits).toHaveLength(MAX_LIVE_ANSWER_HITS);
    expect(hits[0]!.question).toBe(`Question number ${MAX_LIVE_ANSWER_HITS + 4}?`);
  });

  it("clearLiveAnswers empties the store at the meeting boundary", () => {
    const store = createLiveAnswersStore();
    applyAnswersHit(store, GOOD_HIT);
    clearLiveAnswers(store);
    expect(store.getState().hits).toEqual([]);
  });
});
