/**
 * Small fail-closed type guards for validating UNTRUSTED engine payloads
 * field by field. Every inbound frame is untrusted input (prompt-injection /
 * corruption defence); these helpers return null/false on any deviation so a
 * parser can reject rather than coerce a malformed value into the UI.
 */

/** True only for a plain JSON object — arrays, null and primitives fail. */
export function isPlainObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

/** A string, or null. */
export function asString(value: unknown): string | null {
  return typeof value === "string" ? value : null;
}

/** A non-empty string, or null. */
export function asNonEmptyString(value: unknown): string | null {
  return typeof value === "string" && value.length > 0 ? value : null;
}

/** A finite number, or null (rejects NaN / Infinity). */
export function asFiniteNumber(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

/** A boolean, or null. */
export function asBoolean(value: unknown): boolean | null {
  return typeof value === "boolean" ? value : null;
}

/**
 * A finite number or explicit null passthrough (the wire allows `null`), else
 * `undefined` to signal a hard reject. Distinguishes "known-absent" from bad.
 */
export function asFiniteNumberOrNull(value: unknown): number | null | undefined {
  if (value === null) return null;
  return typeof value === "number" && Number.isFinite(value) ? value : undefined;
}
