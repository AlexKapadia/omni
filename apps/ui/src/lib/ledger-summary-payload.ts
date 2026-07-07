/**
 * Fail-closed parser + types for the REAL cost/latency ledger (ledger.summary).
 *
 * Money invariant (binding): every cost is an EXACT decimal STRING as the
 * engine computed it (`total_cost_usd` / `est_cost_usd`). It is kept verbatim
 * as the source of truth and NEVER parsed into a float for arithmetic — the
 * UI may format a string for display, but must never do money math on it.
 */
import {
  asFiniteNumber,
  asNonEmptyString,
  asString,
  isPlainObject,
} from "./untrusted-payload-guards";
// isPlainObject is used by both the row parsers and the top-level guard.

export interface LedgerByProviderRow {
  readonly provider: string;
  readonly totalCalls: number;
  readonly okCalls: number;
  readonly errorCalls: number;
  readonly promptTokens: number;
  readonly completionTokens: number;
  /** Exact decimal string, rendered verbatim. */
  readonly totalCostUsd: string;
  readonly avgLatencyMs: number;
}

export interface LedgerByTaskRow {
  readonly task: string;
  readonly totalCalls: number;
  readonly promptTokens: number;
  readonly completionTokens: number;
  readonly totalCostUsd: string;
  readonly avgLatencyMs: number;
}

export interface LedgerTotals {
  readonly totalCalls: number;
  readonly promptTokens: number;
  readonly completionTokens: number;
  readonly totalCostUsd: string;
}

export interface LedgerRecentEntry {
  readonly ts: string;
  readonly taskType: string;
  readonly provider: string;
  readonly model: string;
  readonly latencyMs: number;
  readonly promptTokens: number;
  readonly completionTokens: number;
  readonly estCostUsd: string;
  readonly outcome: string;
  readonly errorClass: string | null;
}

export interface LedgerSummary {
  readonly byProvider: readonly LedgerByProviderRow[];
  readonly byTask: readonly LedgerByTaskRow[];
  readonly totals: LedgerTotals;
  readonly recent: readonly LedgerRecentEntry[];
}

function parseByProvider(value: unknown): LedgerByProviderRow | null {
  if (!isPlainObject(value)) return null;
  const provider = asNonEmptyString(value["provider"]);
  const totalCalls = asFiniteNumber(value["total_calls"]);
  const okCalls = asFiniteNumber(value["ok_calls"]);
  const errorCalls = asFiniteNumber(value["error_calls"]);
  const promptTokens = asFiniteNumber(value["prompt_tokens"]);
  const completionTokens = asFiniteNumber(value["completion_tokens"]);
  const totalCostUsd = asString(value["total_cost_usd"]);
  const avgLatencyMs = asFiniteNumber(value["avg_latency_ms"]);
  if (provider === null || totalCalls === null || okCalls === null || errorCalls === null) {
    return null;
  }
  if (promptTokens === null || completionTokens === null || totalCostUsd === null) return null;
  if (avgLatencyMs === null) return null;
  return {
    provider,
    totalCalls,
    okCalls,
    errorCalls,
    promptTokens,
    completionTokens,
    totalCostUsd,
    avgLatencyMs,
  };
}

function parseByTask(value: unknown): LedgerByTaskRow | null {
  if (!isPlainObject(value)) return null;
  const task = asNonEmptyString(value["task"]);
  const totalCalls = asFiniteNumber(value["total_calls"]);
  const promptTokens = asFiniteNumber(value["prompt_tokens"]);
  const completionTokens = asFiniteNumber(value["completion_tokens"]);
  const totalCostUsd = asString(value["total_cost_usd"]);
  const avgLatencyMs = asFiniteNumber(value["avg_latency_ms"]);
  if (task === null || totalCalls === null || promptTokens === null) return null;
  if (completionTokens === null || totalCostUsd === null || avgLatencyMs === null) return null;
  return { task, totalCalls, promptTokens, completionTokens, totalCostUsd, avgLatencyMs };
}

function parseTotals(value: unknown): LedgerTotals | null {
  if (!isPlainObject(value)) return null;
  const totalCalls = asFiniteNumber(value["total_calls"]);
  const promptTokens = asFiniteNumber(value["prompt_tokens"]);
  const completionTokens = asFiniteNumber(value["completion_tokens"]);
  const totalCostUsd = asString(value["total_cost_usd"]);
  if (totalCalls === null || promptTokens === null) return null;
  if (completionTokens === null || totalCostUsd === null) return null;
  return { totalCalls, promptTokens, completionTokens, totalCostUsd };
}

function parseRecent(value: unknown): LedgerRecentEntry | null {
  if (!isPlainObject(value)) return null;
  const ts = asNonEmptyString(value["ts"]);
  const taskType = asNonEmptyString(value["task_type"]);
  const provider = asNonEmptyString(value["provider"]);
  const model = asString(value["model"]);
  const latencyMs = asFiniteNumber(value["latency_ms"]);
  const promptTokens = asFiniteNumber(value["prompt_tokens"]);
  const completionTokens = asFiniteNumber(value["completion_tokens"]);
  const estCostUsd = asString(value["est_cost_usd"]);
  const outcome = asNonEmptyString(value["outcome"]);
  const errorClassRaw = value["error_class"];
  const errorClass = errorClassRaw === null ? null : asString(errorClassRaw);
  if (ts === null || taskType === null || provider === null || model === null) return null;
  if (latencyMs === null || promptTokens === null || completionTokens === null) return null;
  if (estCostUsd === null || outcome === null) return null;
  if (errorClass === null && errorClassRaw !== null) return null;
  return {
    ts,
    taskType,
    provider,
    model,
    latencyMs,
    promptTokens,
    completionTokens,
    estCostUsd,
    outcome,
    errorClass,
  };
}

function parseArray<T>(value: unknown, parse: (raw: unknown) => T | null): readonly T[] | null {
  if (!Array.isArray(value)) return null;
  const out: T[] = [];
  for (const raw of value) {
    const item = parse(raw);
    if (item === null) return null;
    out.push(item);
  }
  return out;
}

/** Validate a ledger.summary reply payload fail-closed; null on any deviation. */
export function parseLedgerSummary(payload: Record<string, unknown>): LedgerSummary | null {
  if (!isPlainObject(payload)) return null; // defense in depth
  const byProvider = parseArray(payload["by_provider"], parseByProvider);
  const byTask = parseArray(payload["by_task"], parseByTask);
  const totals = parseTotals(payload["totals"]);
  const recent = parseArray(payload["recent"], parseRecent);
  if (byProvider === null || byTask === null || totals === null || recent === null) return null;
  return { byProvider, byTask, totals, recent };
}
