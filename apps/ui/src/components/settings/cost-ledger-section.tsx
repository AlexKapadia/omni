/**
 * Settings — the REAL cost + latency ledger from ledger.summary. Per-task
 * rows plus a computed-by-the-engine totals row, and a short recent-calls
 * list with honest outcomes.
 *
 * Money invariant (binding): every cost is the engine's EXACT decimal STRING,
 * rendered verbatim — never parsed into a float for arithmetic. Token counts
 * are integer sums (prompt + completion), exact. Loading shows a shimmer
 * (never a spinner); a failed read says so honestly.
 */
import { useStore } from "zustand";
import { SectionLabel } from "../section-label";
import { SkeletonShimmer } from "../skeleton-shimmer";
import { formatTokensCompact } from "../../lib/format-quantities";
import type { SettingsStore } from "../../lib/settings-store";
import type { LedgerByTaskRow, LedgerSummary } from "../../lib/ledger-summary-payload";

const MONO = "font-[family-name:var(--font-mono)]";
const GRID = { gridTemplateColumns: "1.4fr 0.7fr 1fr 0.8fr 0.9fr" } as const;

/** Prepend "$" only when the engine's exact string does not already carry it. */
function displayCost(exact: string): string {
  return exact.startsWith("$") ? exact : `$${exact}`;
}

function taskTokens(row: LedgerByTaskRow): number {
  return row.promptTokens + row.completionTokens; // exact integer sum
}

function LedgerTable({ ledger }: { readonly ledger: LedgerSummary }) {
  const { byTask, totals, recent } = ledger;
  if (byTask.length === 0 && recent.length === 0) {
    return (
      <p className="m-0 text-[var(--ink-secondary)]" style={{ fontSize: "var(--text-meta-size)" }}>
        No model calls yet. The ledger fills as Omni runs.
      </p>
    );
  }
  return (
    <>
      <div
        className="grid border-b border-[var(--ink)] pb-[var(--space-2)] uppercase text-[var(--ink-secondary)]"
        style={{ ...GRID, fontSize: 11, letterSpacing: "var(--label-ls)" }}
      >
        <span>task</span>
        <span className="text-right">calls</span>
        <span className="text-right">tokens</span>
        <span className="text-right">avg</span>
        <span className="text-right">cost</span>
      </div>
      {byTask.map((row) => (
        <div key={row.task} className="grid" style={{ ...GRID, padding: "8px 0" }}>
          <span>{row.task}</span>
          <span className="text-right">{row.totalCalls}</span>
          <span className="text-right">{formatTokensCompact(taskTokens(row))}</span>
          <span className="text-right">{(row.avgLatencyMs / 1000).toFixed(1)}s</span>
          <span className="text-right">{displayCost(row.totalCostUsd)}</span>
        </div>
      ))}
      <div
        className="grid border-t border-[var(--grey-200)] font-medium text-[var(--ink)]"
        style={{ ...GRID, padding: "8px 0 0" }}
      >
        <span>total</span>
        <span className="text-right">{totals.totalCalls}</span>
        <span className="text-right">
          {formatTokensCompact(totals.promptTokens + totals.completionTokens)}
        </span>
        <span className="text-right">—</span>
        <span className="text-right">{displayCost(totals.totalCostUsd)}</span>
      </div>
    </>
  );
}

export function CostLatencyLedgerSection({ store }: { readonly store: SettingsStore }) {
  const phase = useStore(store, (s) => s.ledgerPhase);
  const error = useStore(store, (s) => s.ledgerError);
  const ledger = useStore(store, (s) => s.ledger);
  return (
    <section aria-label="Cost and latency" className="flex flex-col gap-[var(--space-2)]">
      <SectionLabel>Cost + latency</SectionLabel>
      <div
        className={`border border-[var(--grey-200)] ${MONO} text-[var(--grey-600)]`}
        style={{ borderRadius: "var(--radius-card)", padding: 20, fontSize: "var(--text-meta-size)" }}
      >
        {phase === "loading" ? (
          <SkeletonShimmer lines={3} />
        ) : phase === "error" ? (
          <p role="alert" className="m-0 text-[var(--grey-600)]">
            {error ?? "The engine did not send the ledger."}
          </p>
        ) : ledger !== null ? (
          <LedgerTable ledger={ledger} />
        ) : null}
      </div>
    </section>
  );
}
