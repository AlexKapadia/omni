/**
 * Fail-closed parser for ``import.media.progress`` engine events.
 */
import { asFiniteNumber, asNonEmptyString, isPlainObject } from "./untrusted-payload-guards";

export const IMPORT_MEDIA_PROGRESS_EVENT = "import.media.progress";

export interface ImportMediaProgress {
  readonly stage: string;
  readonly fraction: number;
  readonly percent: number;
}

/** Validate an import.media.progress payload; null on any deviation. */
export function parseImportMediaProgressPayload(
  payload: unknown,
): ImportMediaProgress | null {
  if (!isPlainObject(payload)) return null;
  const stage = asNonEmptyString(payload["stage"]);
  const fraction = asFiniteNumber(payload["fraction"]);
  if (stage === null || fraction === null) return null;
  if (fraction < 0 || fraction > 1) return null;
  return {
    stage,
    fraction,
    percent: Math.round(fraction * 100),
  };
}
