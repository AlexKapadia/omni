/**
 * Ollama surface for the summary model section (Meetily-style): the local
 * model catalog shown before any real list arrives, plus fail-closed parsers
 * for the `ollama.models.list` reply and the streaming `ollama.pull.*`
 * events. Mirrors models-download-events.ts's discipline — a malformed
 * frame is dropped whole, never partially coerced into the UI.
 */
import {
  asBoolean,
  asFiniteNumber,
  asFiniteNumberOrNull,
  asNonEmptyString,
  asString,
  isPlainObject,
} from "./untrusted-payload-guards";

/** Known-good local models offered before the user lists what's installed. */
export interface OllamaModelOption {
  readonly id: string;
  readonly label: string;
}

export const OLLAMA_MODEL_OPTIONS: readonly OllamaModelOption[] = [
  { id: "llama3.2", label: "Llama 3.2 (3B)" },
  { id: "gemma3:1b", label: "Gemma 3 (1B)" },
];

export const DEFAULT_OLLAMA_MODEL_ID = "llama3.2";

// ------------------------------------------------------- ollama.models.list
export interface OllamaModel {
  readonly name: string;
  readonly sizeBytes: number | null;
}

/** null on any deviation — a corrupt list must never populate the picker. */
export function parseOllamaModelsList(payload: Record<string, unknown>): readonly OllamaModel[] | null {
  const raw = payload["models"];
  if (!Array.isArray(raw)) return null;
  const out: OllamaModel[] = [];
  for (const item of raw) {
    if (!isPlainObject(item)) return null;
    const name = asNonEmptyString(item["name"]);
    if (name === null) return null;
    const sizeBytes = asFiniteNumberOrNull(item["size"]);
    if (sizeBytes === undefined) return null;
    out.push({ name, sizeBytes });
  }
  return out;
}

// --------------------------------------------------------- ollama.pull.* events
export interface OllamaPullProgress {
  readonly model: string;
  readonly receivedBytes: number;
  readonly totalBytes: number | null;
}

export interface OllamaPullFailed {
  readonly model: string;
  readonly message: string;
}

export interface OllamaPullCompleted {
  readonly ok: boolean;
  readonly model: string;
}

export function parseOllamaPullProgress(payload: Record<string, unknown>): OllamaPullProgress | null {
  const model = asNonEmptyString(payload["model"]);
  const receivedBytes = asFiniteNumber(payload["received_bytes"]);
  const totalBytes = asFiniteNumberOrNull(payload["total_bytes"]);
  if (model === null || receivedBytes === null || receivedBytes < 0) return null;
  if (totalBytes === undefined) return null; // neither number nor null → reject
  return { model, receivedBytes, totalBytes };
}

export function parseOllamaPullFailed(payload: Record<string, unknown>): OllamaPullFailed | null {
  const model = asNonEmptyString(payload["model"]);
  const message = asString(payload["message"]);
  if (model === null || message === null) return null;
  return { model, message };
}

export function parseOllamaPullCompleted(payload: Record<string, unknown>): OllamaPullCompleted | null {
  const ok = asBoolean(payload["ok"]);
  const model = asNonEmptyString(payload["model"]);
  if (ok === null || model === null) return null;
  return { ok, model };
}

// ------------------------------------------------------------- ollama.ping
/**
 * Mirrors `ping_ollama`'s real reply shape: `{ok: true, version}` on success,
 * `{ok: false, error}` on any connection failure — never a "message" field.
 */
export interface OllamaPingResult {
  readonly ok: boolean;
  readonly version: string | null;
  readonly error: string | null;
}

export function parseOllamaPingResult(payload: Record<string, unknown>): OllamaPingResult | null {
  const ok = asBoolean(payload["ok"]);
  if (ok === null) return null;
  return { ok, version: asString(payload["version"]), error: asString(payload["error"]) };
}
