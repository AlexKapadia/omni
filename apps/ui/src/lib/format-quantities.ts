/**
 * Exact display formatting for the quantities the UI shows: token counts,
 * costs held in integer cents, durations, and relative meeting times.
 *
 * Deterministic-path mandate: money is integer-cent arithmetic end to end —
 * formatting never rounds through floating dollars.
 */

/** 1_210_000 -> "1.21M", 246_000 -> "246K", 374 -> "374". Floors at 2dp/0dp. */
export function formatTokensCompact(tokens: number): string {
  if (!Number.isFinite(tokens) || tokens < 0) return "0";
  if (tokens >= 1_000_000) return `${(Math.floor(tokens / 10_000) / 100).toFixed(2)}M`;
  if (tokens >= 1_000) return `${Math.floor(tokens / 1_000)}K`;
  return String(Math.floor(tokens));
}

/** 412 cents -> "$4.12". Integer maths only — exact to the cent. */
export function formatCentsUsd(cents: number): string {
  const whole = Math.floor(cents / 100);
  const rest = cents % 100;
  return `$${whole}.${String(rest).padStart(2, "0")}`;
}

/** 47 -> "47 min", 130 -> "2 h 10 min", 120 -> "2 h". */
export function formatDurationMin(minutes: number): string {
  const total = Math.max(0, Math.floor(minutes));
  const h = Math.floor(total / 60);
  const m = total % 60;
  if (h === 0) return `${m} min`;
  if (m === 0) return `${h} h`;
  return `${h} h ${m} min`;
}

/** ISO start -> "14:00" local wall-clock label for a library row. */
export function formatClockShort(startIso: string): string {
  const date = new Date(startIso);
  if (Number.isNaN(date.getTime())) return "--:--";
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

/** Day bucket for library dividers: "Today", "Yesterday", else "Mon 29 Jun". */
export function formatDayLabel(startIso: string, nowMs: number = Date.now()): string {
  const date = new Date(startIso);
  if (Number.isNaN(date.getTime())) return "Unknown day";
  const startOfDay = (d: Date) => new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime();
  const dayDelta = Math.round((startOfDay(new Date(nowMs)) - startOfDay(date)) / 86_400_000);
  if (dayDelta <= 0) return "Today"; // future meetings sit under Today
  if (dayDelta === 1) return "Yesterday";
  return date.toLocaleDateString(undefined, { weekday: "short", day: "numeric", month: "short" });
}

/** Minutes until a future start: "in 40 min" / "in 2 h 5 min"; null if past. */
export function formatStartsIn(startIso: string, nowMs: number = Date.now()): string | null {
  const startMs = new Date(startIso).getTime();
  if (Number.isNaN(startMs) || startMs <= nowMs) return null;
  const minutes = Math.ceil((startMs - nowMs) / 60_000);
  return `in ${formatDurationMin(minutes)}`;
}
