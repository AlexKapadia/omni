/**
 * Fuzz-tolerant parser for the LLM's self-tagged affect line
 * (docs/design/naomi-visual-brief.md §3): the response stream opens with
 * `<<affect v=+0.6 a=0.7 burst=laugh?>>` which must be stripped before
 * display/TTS.
 *
 * Security posture: the tag rides inside MODEL OUTPUT, which is downstream
 * of untrusted transcript/document content — prompt-injection discipline
 * (claude.md §5.6) applies. This parser therefore:
 *   - never throws (malformed → null → caller falls back to prosody);
 *   - never returns any substring of the tag for display or TTS — only the
 *     clamped numeric triple and the remaining text AFTER the tag;
 *   - bounds how much text it will scan, so a hostile "tag" cannot make it
 *     do unbounded work.
 */

import { type Affect, clampAffect } from "./naomi-affect-types";

/** A parse outcome: the affect (or null → prosody fallback) plus the text
 *  with the tag removed. `text` is ALWAYS safe to display/speak. */
export interface AffectTagParseResult {
  readonly affect: Affect | null;
  readonly text: string;
}

// The tag must open the response (whitespace tolerated). Bounded quantifiers
// throughout — no catastrophic backtracking on hostile input.
const TAG_PATTERN = /^\s{0,16}<<\s{0,8}affect\b([^>]{0,160})>>/i;

// Field extractors, each tolerant of sign, spaces and decimal forms.
const VALENCE_PATTERN = /\bv\s{0,4}=\s{0,4}([+-]?\d{0,6}(?:\.\d{1,6})?)/i;
const AROUSAL_PATTERN = /\ba\s{0,4}=\s{0,4}([+-]?\d{0,6}(?:\.\d{1,6})?)/i;
const BURST_PATTERN = /\bburst\s{0,4}=\s{0,4}(laugh)\b\s{0,4}(?:\(\s{0,4}([+-]?\d{0,6}(?:\.\d{1,6})?)\s{0,4}\))?/i;

/**
 * Parse (and strip) a leading affect tag from one chunk of model output.
 *
 * Contract: NEVER crashes; on any malformation the affect is null and the
 * MALFORMED TAG IS STILL STRIPPED when it structurally looks like one
 * (`<<...>>` opener) so broken tag text can never leak to TTS or display.
 */
export function parseLeadingAffectTag(raw: unknown): AffectTagParseResult {
  if (typeof raw !== "string") return { affect: null, text: "" }; // fail closed
  const match = TAG_PATTERN.exec(raw);
  if (match === null) {
    // No structural tag opener. One hostile shape remains: an UNCLOSED
    // `<<affect ...` prefix would otherwise flow into TTS — strip to the
    // end of its line instead (never speak tag syntax).
    const unclosed = /^\s{0,16}<<\s{0,8}affect\b[^\n]{0,200}/i.exec(raw);
    if (unclosed !== null) {
      return { affect: null, text: raw.slice(unclosed[0].length).trimStart() };
    }
    return { affect: null, text: raw };
  }
  const body = match[1] ?? "";
  const remainder = raw.slice(match[0].length).trimStart();
  const valenceMatch = VALENCE_PATTERN.exec(body);
  const arousalMatch = AROUSAL_PATTERN.exec(body);
  const valence = Number.parseFloat(valenceMatch?.[1] ?? "");
  const arousal = Number.parseFloat(arousalMatch?.[1] ?? "");
  // Both axes must be real numbers; otherwise the tag is malformed and the
  // caller must use the prosody fallback (fail open to NEUTRAL, per brief).
  if (!Number.isFinite(valence) || !Number.isFinite(arousal)) {
    return { affect: null, text: remainder };
  }
  const burstMatch = BURST_PATTERN.exec(body);
  const burstIntensityRaw = Number.parseFloat(burstMatch?.[2] ?? "");
  const burst =
    burstMatch === null
      ? null
      : ({
          kind: "laugh",
          // `burst=laugh` without a parenthesised intensity = a full laugh.
          intensity: Number.isFinite(burstIntensityRaw) ? burstIntensityRaw : 1,
        } as const);
  return { affect: clampAffect(valence, arousal, burst), text: remainder };
}

/**
 * Prosody fallback (brief §3): when the tag is missing/malformed — arousal
 * from the observed TTS envelope mean and speaking rate, valence 0.
 * Pure arithmetic so it is exactly testable.
 */
export function prosodyFallbackAffect(envelopeMean: number, wordsPerSecond: number): Affect {
  // Envelope contributes up to 0.6, speaking rate up to 0.4 (≥4 w/s is fast).
  const arousal = 0.6 * Math.min(Math.max(envelopeMean, 0), 1)
    + 0.4 * Math.min(Math.max(wordsPerSecond / 4, 0), 1);
  return clampAffect(0, arousal, null);
}
