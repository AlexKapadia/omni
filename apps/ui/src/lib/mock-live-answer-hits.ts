/**
 * MOCK live-answer source — synthetic Answers-panel hits until the M3 live
 * retrieval tier (route + hybrid RRF over the vault index, <2 s budget)
 * produces real ones from the running transcript.
 *
 * Clearly-marked mock per the swappable-data-layer contract: the hit shape
 * (question heard, answer prose, exact vault source) is what the real
 * pipeline emits. Trigger heuristic: a finalised "them" segment that ends
 * with a question mark yields a hit — deterministic and driven by the REAL
 * transcript store, so the panel behaviour (motion, collapse, source line)
 * is exercised end-to-end. Synthetic vault paths only.
 */
import type { AskProseSpan } from "./ask-store";
import type { TranscriptSegment } from "./transcript-store";

export interface LiveAnswerHit {
  /** The segment that triggered the hit — stable id for render keys. */
  readonly id: string;
  /** The question as heard, quoted verbatim in the panel. */
  readonly questionHeard: string;
  readonly answerProse: readonly AskProseSpan[];
  /** Exact source line per the citation contract: path + human context. */
  readonly sourcePath: string;
  readonly sourceContext: string;
}

/**
 * Derive the newest mock hit from finalised segments, or null when no
 * "them" question has been heard yet (the panel's honest idle state).
 */
export function deriveMockLiveAnswerHit(
  segments: readonly TranscriptSegment[],
): LiveAnswerHit | null {
  for (let i = segments.length - 1; i >= 0; i -= 1) {
    const segment = segments[i];
    if (segment === undefined || segment.stream !== "them") continue;
    const text = segment.text.trim();
    if (!text.endsWith("?")) continue;
    return {
      id: segment.segmentId,
      questionHeard: text,
      // MOCK prose — the real answer comes from the live retrieval tier.
      answerProse: [
        { text: "Last discussed on " },
        { text: "July 14 with the Northwind team", strong: true },
        { text: " — the renewal covers the single-tenant plan at $84,000 a year." },
      ],
      sourcePath: "vault/clients/northwind.md",
      sourceContext: "2025-07-14 renewal call",
    };
  }
  return null;
}
