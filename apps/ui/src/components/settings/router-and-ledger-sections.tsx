/**
 * Settings — the AI router matrix and the cost/latency ledger (components
 * doc §10). The matrix is REAL routing policy from settings-store (radio per
 * allowed provider, deny-by-default cells rendered as an em dash); ledger
 * rows are MOCK numbers (mock-settings-data.ts) with the total row COMPUTED
 * by ledgerTotals — never hand-written (zero-numerical-error mandate).
 */
import { useStore } from "zustand";
import { SettingsGroupCard } from "./settings-group-card";
import { SectionLabel } from "../section-label";
import { formatCentsUsd, formatTokensCompact } from "../../lib/format-quantities";
import { LEDGER_MOCK_CAPTION } from "../../lib/mock-settings-data";
import {
  ledgerTotals,
  setRoutingProvider,
  type RoutingProvider,
  type SettingsStore,
} from "../../lib/settings-store";

const PROVIDERS: readonly RoutingProvider[] = ["local", "groq", "gemini", "claude"];

const MONO_12 = "font-[family-name:var(--font-mono)]";

function RadioDot({ selected }: { readonly selected: boolean }) {
  return (
    <span
      aria-hidden
      className={selected ? "bg-[var(--ink)]" : "border border-[var(--grey-300)]"}
      style={{ display: "inline-block", width: 10, height: 10, borderRadius: "50%" }}
    />
  );
}

export function RouterMatrixSection({ store }: { readonly store: SettingsStore }) {
  const routing = useStore(store, (s) => s.routing);
  const killSwitch = useStore(store, (s) => s.killSwitch);
  return (
    <SettingsGroupCard label="AI router">
      <div
        role="table"
        aria-label="Routing table"
        className={`${MONO_12} text-[var(--grey-600)]`}
        style={{ fontSize: "var(--text-meta-size)", padding: "14px 0" }}
      >
        <div
          role="row"
          className="grid items-center border-b border-[var(--ink)] pb-[var(--space-2)] uppercase text-[var(--grey-400)]"
          style={{ gridTemplateColumns: "1.4fr 1fr 1fr 1fr 1fr", fontSize: 11, letterSpacing: "var(--label-ls)" }}
        >
          <span role="columnheader">task</span>
          {PROVIDERS.map((p) => (
            <span role="columnheader" key={p} className="text-center">
              {p}
            </span>
          ))}
        </div>
        {routing.map((row) => (
          <div
            role="row"
            key={row.task}
            className="grid items-center"
            style={{ gridTemplateColumns: "1.4fr 1fr 1fr 1fr 1fr", padding: "10px 0" }}
          >
            <span role="rowheader">{row.task}</span>
            {PROVIDERS.map((provider) =>
              row.allowed.includes(provider) ? (
                <button
                  key={provider}
                  type="button"
                  role="radio"
                  aria-checked={row.provider === provider}
                  aria-label={`route ${row.task} to ${provider}`}
                  onClick={() => setRoutingProvider(store, row.task, provider)}
                  className="cursor-pointer border-none bg-transparent text-center"
                >
                  <RadioDot selected={row.provider === provider} />
                </button>
              ) : (
                // Deny by default: this task may not route here at all.
                <span key={provider} className="text-center text-[var(--grey-300)]" aria-hidden>
                  —
                </span>
              ),
            )}
          </div>
        ))}
        {killSwitch && (
          <p className="m-0 pt-[var(--space-2)] text-[var(--grey-600)]" style={{ fontSize: 11 }}>
            Kill switch engaged — every external route above is refused until it is released.
          </p>
        )}
      </div>
    </SettingsGroupCard>
  );
}

export function CostLatencyLedgerSection({ store }: { readonly store: SettingsStore }) {
  const ledger = useStore(store, (s) => s.ledger);
  const totals = ledgerTotals(ledger);
  const grid = { gridTemplateColumns: "1.4fr 0.8fr 1fr 0.8fr 0.8fr" } as const;
  return (
    <section aria-label="Cost and latency" className="flex flex-col gap-[var(--space-2)]">
      <SectionLabel>Cost + latency — last 30 days</SectionLabel>
      <div
        className={`border border-[var(--grey-200)] ${MONO_12} text-[var(--grey-600)]`}
        style={{ borderRadius: "var(--radius-card)", padding: 20, fontSize: "var(--text-meta-size)" }}
      >
        <div
          className="grid border-b border-[var(--ink)] pb-[var(--space-2)] uppercase text-[var(--grey-400)]"
          style={{ ...grid, fontSize: 11, letterSpacing: "var(--label-ls)" }}
        >
          <span>task</span>
          <span className="text-right">calls</span>
          <span className="text-right">tokens</span>
          <span className="text-right">p50</span>
          <span className="text-right">cost</span>
        </div>
        {ledger.map((row) => (
          <div key={row.task} className="grid" style={{ ...grid, padding: "8px 0" }}>
            <span>{row.task}</span>
            <span className="text-right">{row.calls}</span>
            <span className="text-right">{formatTokensCompact(row.tokens)}</span>
            <span className="text-right">
              {row.p50Seconds !== null ? `${row.p50Seconds.toFixed(1)}s` : "—"}
            </span>
            <span className="text-right">{formatCentsUsd(row.costCents)}</span>
          </div>
        ))}
        <div
          className="grid border-t border-[var(--grey-200)] font-medium text-[var(--ink)]"
          style={{ ...grid, padding: "8px 0 0" }}
        >
          <span>total</span>
          <span className="text-right">{totals.calls}</span>
          <span className="text-right">{formatTokensCompact(totals.tokens)}</span>
          <span className="text-right">—</span>
          <span className="text-right">{formatCentsUsd(totals.costCents)}</span>
        </div>
        <p className="m-0 pt-[var(--space-3)] text-[var(--grey-400)]" style={{ fontSize: 11 }}>
          {LEDGER_MOCK_CAPTION}
        </p>
      </div>
    </section>
  );
}
