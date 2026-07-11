/**
 * Format the idle pill hold hint from push-to-talk hotkey tokens.
 * Empty / missing → default F9 (matches the shell's startup binding).
 */
export function formatHoldLabel(keys: readonly string[] | undefined | null): string {
  if (keys === undefined || keys === null || keys.length === 0) return "Hold F9";
  return `Hold ${keys.join("+")}`;
}
