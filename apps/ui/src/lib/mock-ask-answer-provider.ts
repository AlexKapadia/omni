/**
 * MOCK AskAnswerProvider — deterministic synthetic answers until the M3
 * retrieval pipeline (hybrid FTS5+vector retrieval with exact file+line
 * citations) implements the same interface.
 *
 * Clearly-marked mock per the swappable-data-layer contract. Answers echo the
 * question and carry real-shaped citations (note_path + line range +
 * heading_path per the M3 §Cite contract). Deterministic: the same question
 * always yields the same answer. Synthetic vault paths only — no PII.
 */
import type { AskAnswer, AskAnswerProvider } from "./ask-store";

/** Small delay so the thinking shimmer is a real state, not a flash. */
const MOCK_LATENCY_MS = 600;

/** Tiny deterministic hash to vary the canned answer by question. */
function hashQuestion(question: string): number {
  let h = 0;
  for (let i = 0; i < question.length; i += 1) {
    h = (h * 31 + question.charCodeAt(i)) >>> 0;
  }
  return h;
}

const CANNED_ANSWERS: readonly AskAnswer[] = [
  {
    headline: "Northwind renewal",
    prose: [
      { text: "Northwind's renewal is priced at " },
      { text: "$84,000 for the single-tenant plan", strong: true, citationMarker: 1 },
      { text: ", up from $71,500 last year. Marcus asked for a security review before signature; " },
      { text: "the review is scheduled for July 14", strong: true, citationMarker: 2 },
      { text: "." },
    ],
    citations: [
      {
        marker: 1,
        notePath: "vault/clients/northwind.md",
        lineStart: 42,
        lineEnd: 58,
        headingPath: "Northwind › Renewal 2026",
        snippet: "Renewal quote: $84,000/yr single-tenant. Last year $71,500 multi-tenant.",
      },
      {
        marker: 2,
        notePath: "vault/meetings/2026-07-06-vendor-call-northwind.md",
        lineStart: 118,
        lineEnd: 124,
        headingPath: "Vendor call › Next steps",
        snippet: "Marcus: security review first — pencilled for Jul 14 with their infra team.",
      },
    ],
  },
  {
    headline: "Hiring loop status",
    prose: [
      { text: "The staff engineer loop has " },
      { text: "two of four rounds complete", strong: true, citationMarker: 1 },
      { text: ". Systems design was strong; the routing deep-dive is the open follow-up, owned by Elena" },
      { text: "", citationMarker: 2 },
      { text: "." },
    ],
    citations: [
      {
        marker: 1,
        notePath: "vault/hiring/staff-engineer-loop.md",
        lineStart: 9,
        lineEnd: 15,
        headingPath: "Loop › Progress",
        snippet: "Rounds done: systems design ✓, coding ✓. Remaining: routing deep-dive, values.",
      },
      {
        marker: 2,
        notePath: "vault/meetings/2026-07-05-1-1-elena.md",
        lineStart: 31,
        lineEnd: 34,
        headingPath: "1:1 › Actions",
        snippet: "Elena to run the routing deep-dive follow-up this week.",
      },
    ],
  },
];

export function createMockAskAnswerProvider(): AskAnswerProvider {
  return {
    answer: (question: string) =>
      new Promise((resolve) => {
        // Length is a compile-time constant > 0, but index fail-safe anyway.
        const canned =
          CANNED_ANSWERS[hashQuestion(question) % CANNED_ANSWERS.length] ?? CANNED_ANSWERS[0]!;
        setTimeout(() => resolve(canned), MOCK_LATENCY_MS);
      }),
  };
}
