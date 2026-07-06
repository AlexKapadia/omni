/**
 * Bridge from the design-agent-owned CSS duration tokens (tokens.css) to
 * framer-motion, which needs numbers, not CSS strings.
 *
 * Why: the token contract says durations come ONLY from --dur-micro/--dur-page.
 * Framer cannot read CSS custom properties for transition durations, so we read
 * the computed value at runtime. If the token is missing (tokens.css not loaded,
 * e.g. in unit tests), we return 0 — no token, no motion. That is fail-safe and
 * never invents a hard-coded duration.
 */

export type DurationToken = "--dur-micro" | "--dur-page";

const cache = new Map<DurationToken, number>();

/** Parse "150ms" / "0.15s" → seconds. Unparseable or missing → 0. */
function parseCssDuration(value: string): number {
  const trimmed = value.trim();
  if (trimmed.endsWith("ms")) {
    const ms = Number.parseFloat(trimmed);
    return Number.isFinite(ms) && ms >= 0 ? ms / 1000 : 0;
  }
  if (trimmed.endsWith("s")) {
    const s = Number.parseFloat(trimmed);
    return Number.isFinite(s) && s >= 0 ? s : 0;
  }
  return 0;
}

/** Duration of a design token in seconds, for framer-motion transitions. */
export function tokenDurationSeconds(token: DurationToken): number {
  const cached = cache.get(token);
  if (cached !== undefined) return cached;
  const raw = getComputedStyle(document.documentElement).getPropertyValue(token);
  const seconds = parseCssDuration(raw);
  cache.set(token, seconds);
  return seconds;
}
