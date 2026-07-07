/**
 * Fail-closed tests for the ledger.summary parser. The money invariant: cost
 * strings are preserved VERBATIM (never numericised), and any malformed row
 * rejects the whole payload.
 */
import { describe, expect, it } from "vitest";
import { parseLedgerSummary } from "./ledger-summary-payload";

const GOOD = {
  by_provider: [
    {
      provider: "gemini",
      total_calls: 92,
      ok_calls: 90,
      error_calls: 2,
      prompt_tokens: 1_200_000,
      completion_tokens: 10_000,
      total_cost_usd: "4.1234",
      avg_latency_ms: 3800,
    },
  ],
  by_task: [
    {
      task: "note enhancement",
      total_calls: 92,
      prompt_tokens: 1_200_000,
      completion_tokens: 10_000,
      total_cost_usd: "4.1234",
      avg_latency_ms: 3800,
    },
  ],
  totals: { total_calls: 92, prompt_tokens: 1_200_000, completion_tokens: 10_000, total_cost_usd: "4.1234" },
  recent: [
    {
      ts: "2026-07-06T14:00:00Z",
      task_type: "note_enhancement",
      provider: "gemini",
      model: "flash",
      latency_ms: 3800,
      prompt_tokens: 12000,
      completion_tokens: 300,
      est_cost_usd: "0.0041",
      outcome: "ok",
      error_class: null,
    },
  ],
};

describe("parseLedgerSummary", () => {
  it("accepts the pinned shape and preserves cost strings verbatim", () => {
    const summary = parseLedgerSummary(GOOD);
    expect(summary).not.toBeNull();
    expect(summary!.totals.totalCostUsd).toBe("4.1234"); // exact string, not a float
    expect(summary!.byTask[0]!.totalCostUsd).toBe("4.1234");
    expect(summary!.recent[0]!.estCostUsd).toBe("0.0041");
    expect(summary!.recent[0]!.errorClass).toBeNull();
  });

  it("accepts an honestly empty ledger", () => {
    const summary = parseLedgerSummary({ by_provider: [], by_task: [], totals: { total_calls: 0, prompt_tokens: 0, completion_tokens: 0, total_cost_usd: "0" }, recent: [] });
    expect(summary!.byTask).toEqual([]);
  });

  it("keeps a non-null error_class string", () => {
    const summary = parseLedgerSummary({
      ...GOOD,
      recent: [{ ...GOOD.recent[0], error_class: "rate_limit" }],
    });
    expect(summary!.recent[0]!.errorClass).toBe("rate_limit");
  });

  it.each<[string, unknown]>([
    ["by_provider not an array", { ...GOOD, by_provider: {} }],
    ["a task cost not a string", { ...GOOD, by_task: [{ ...GOOD.by_task[0], total_cost_usd: 4.12 }] }],
    ["a task total_calls not a number", { ...GOOD, by_task: [{ ...GOOD.by_task[0], total_calls: "many" }] }],
    ["totals cost missing", { ...GOOD, totals: { total_calls: 1, prompt_tokens: 1, completion_tokens: 1 } }],
    ["recent latency not a number", { ...GOOD, recent: [{ ...GOOD.recent[0], latency_ms: "slow" }] }],
    ["recent est_cost not a string", { ...GOOD, recent: [{ ...GOOD.recent[0], est_cost_usd: 0.004 }] }],
  ])("rejects %s", (_label, payload) => {
    expect(parseLedgerSummary(payload as Record<string, unknown>)).toBeNull();
  });
});
