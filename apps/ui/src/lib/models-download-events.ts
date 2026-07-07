/**
 * Fail-closed parsers + types for the streaming model-download events and the
 * Google-connect completion event. These are EVENTS (correlated by name, not
 * a single reply), so onboarding step 4 subscribes and renders real progress
 * as bytes arrive — never a fabricated bar.
 */
import {
  asBoolean,
  asFiniteNumber,
  asFiniteNumberOrNull,
  asNonEmptyString,
  asString,
} from "./untrusted-payload-guards";

export interface ModelsDownloadProgress {
  readonly file: string;
  readonly receivedBytes: number;
  readonly totalBytes: number | null;
  readonly sha256Verified: boolean | null;
}

export interface ModelsDownloadFailed {
  readonly file: string;
  readonly message: string;
}

export interface ModelsDownloadCompleted {
  readonly ok: boolean;
  readonly files: readonly string[];
}

export interface GoogleConnectCompleted {
  readonly ok: boolean;
  readonly message: string;
}

/** null on any deviation — a corrupt progress frame must not move a bar. */
export function parseModelsProgress(payload: Record<string, unknown>): ModelsDownloadProgress | null {
  const file = asNonEmptyString(payload["file"]);
  const receivedBytes = asFiniteNumber(payload["received_bytes"]);
  const totalBytes = asFiniteNumberOrNull(payload["total_bytes"]);
  const shaRaw = payload["sha256_verified"];
  const sha256Verified = shaRaw === null ? null : asBoolean(shaRaw);
  if (file === null || receivedBytes === null || receivedBytes < 0) return null;
  if (totalBytes === undefined) return null; // neither number nor null → reject
  if (sha256Verified === null && shaRaw !== null) return null;
  return { file, receivedBytes, totalBytes, sha256Verified };
}

export function parseModelsFailed(payload: Record<string, unknown>): ModelsDownloadFailed | null {
  const file = asNonEmptyString(payload["file"]);
  const message = asString(payload["message"]);
  if (file === null || message === null) return null;
  return { file, message };
}

export function parseModelsCompleted(
  payload: Record<string, unknown>,
): ModelsDownloadCompleted | null {
  const ok = asBoolean(payload["ok"]);
  const filesRaw = payload["files"];
  if (ok === null || !Array.isArray(filesRaw)) return null;
  const files: string[] = [];
  for (const item of filesRaw) {
    if (typeof item !== "string") return null; // fail closed
    files.push(item);
  }
  return { ok, files };
}

export function parseGoogleCompleted(payload: Record<string, unknown>): GoogleConnectCompleted | null {
  const ok = asBoolean(payload["ok"]);
  const message = asString(payload["message"]);
  if (ok === null || message === null) return null;
  return { ok, message };
}
