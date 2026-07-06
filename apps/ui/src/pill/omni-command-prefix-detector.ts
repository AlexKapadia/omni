/**
 * Live wake-word detector for the pill's mode chip — a TypeScript MIRROR of
 * engine/dictation/dictation_mode_splitter.py (which is AUTHORITATIVE).
 *
 * The pill flips its chip to COMMAND the moment a partial transcript starts
 * with the wake word; the engine re-decides on release. The two must agree,
 * so the rules are transcribed 1:1: leading whitespace/punctuation ignored,
 * the FIRST WORD (maximal alphanumeric run) must fold to "omni"
 * (case-insensitive, accent-insensitive), and a hyphen glued to a following
 * letter ("omni-channel") keeps it ONE word — not a wake word.
 */

export const WAKE_WORD = "omni";

// Mirrors _LEADING_TRIM in the Python splitter (STT/user front-punctuation).
const LEADING_TRIM = new Set([
  ..." \t\r\n\"'“”‘’.,:;!?…—–-()[]{}",
]);

// Mirrors _WORD_HYPHENS: hyphen/en-dash/em-dash glue words together.
const WORD_HYPHENS = new Set(["-", "–", "—"]);

/** Letter-or-digit test (unicode-aware), mirroring Python's str.isalnum. */
function isAlnum(ch: string): boolean {
  return /[\p{L}\p{N}]/u.test(ch);
}

/** Casefold + strip combining accents, for comparison ONLY (never a rewrite). */
function foldWord(word: string): string {
  return word
    .normalize("NFKD")
    .replace(/\p{M}/gu, "")
    .toLowerCase();
}

/**
 * True when the (possibly partial) transcript is addressed to Omni.
 * Fail-safe direction: anything ambiguous is NOT a command — notes are the
 * safe default, matching the engine's deny-by-default posture.
 */
export function detectOmniCommandPrefix(text: string): boolean {
  // charAt returns "" past the end, which fails both set/regex tests —
  // keeping the scans total without unchecked index access.
  let start = 0;
  while (start < text.length && LEADING_TRIM.has(text.charAt(start))) start += 1;
  let end = start;
  while (end < text.length && isAlnum(text.charAt(end))) end += 1;
  const firstWord = text.slice(start, end);
  if (firstWord.length === 0) return false;
  // Hyphenated continuation ("omni-channel"): one word, not the wake word.
  const hyphenContinuesWord =
    WORD_HYPHENS.has(text.charAt(end)) && isAlnum(text.charAt(end + 1));
  if (hyphenContinuesWord) return false;
  return foldWord(firstWord) === WAKE_WORD;
}
