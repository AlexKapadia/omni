/**
 * Settings — the AI router matrix. Read-only display of the REAL resolved
 * routing policy from settings.get: per task, whether it runs on-device, the
 * ordered provider→model fallback chain, and the latency budget. When the
 * kill switch is engaged the card discloses that cloud routes are
 * refused (fail closed on egress; local Ollama may still run).
 *
 * The design doc's provider/model copy is stale by contract — every value here
 * is the engine's own resolved policy, never invented.
 */
import { useStore } from "zustand";
import { SettingsGroupCard } from "./settings-group-card";
import { SkeletonShimmer } from "../skeleton-shimmer";
import type { RoutingRow, SettingsStore } from "../../lib/settings-store";

const MONO = "font-[family-name:var(--font-mono)]";

function AttemptChain({ row }: { readonly row: RoutingRow }) {
  if (row.attempts.length === 0) {
    return <span className="text-[var(--ink-secondary)]">—</span>;
  }
  return (
    <span className="text-[var(--grey-600)]">
      {row.attempts.map((attempt, index) => (
        <span key={`${attempt.provider}:${attempt.model}:${index}`}>
          {index > 0 && <span className="text-[var(--grey-300)]"> → </span>}
          {attempt.provider}
          {attempt.model.length > 0 && (
            <span className="text-[var(--ink-secondary)]"> · {attempt.model}</span>
          )}
        </span>
      ))}
    </span>
  );
}

export function RouterMatrixSection({ store }: { readonly store: SettingsStore }) {
  const phase = useStore(store, (s) => s.settingsPhase);
  const error = useStore(store, (s) => s.settingsError);
  const routing = useStore(store, (s) => s.routing);
  const killSwitchEngaged = useStore(store, (s) => s.killSwitchEngaged);

  return (
    <SettingsGroupCard label="AI providers">
      {phase === "loading" ? (
        <div style={{ padding: "14px 0" }}>
          <SkeletonShimmer lines={3} />
        </div>
      ) : phase === "error" ? (
        <p
          role="alert"
          className="m-0 text-[var(--grey-600)]"
          style={{ padding: "14px 0", fontSize: "var(--text-meta-size)" }}
        >
          {error ?? "The engine did not send the routing policy."}
        </p>
      ) : (
        <div
          role="table"
          aria-label="Routing policy"
          className={`${MONO} text-[var(--grey-600)]`}
          style={{ fontSize: "var(--text-meta-size)", padding: "14px 0" }}
        >
          <div
            role="row"
            className="grid items-center border-b border-[var(--ink)] pb-[var(--space-2)] uppercase text-[var(--ink-secondary)]"
            style={{ gridTemplateColumns: "1fr 1.6fr 0.6fr", fontSize: 11, letterSpacing: "var(--label-ls)" }}
          >
            <span role="columnheader">task</span>
            <span role="columnheader">route</span>
            <span role="columnheader" className="text-right">
              budget
            </span>
          </div>
          {routing.map((row) => (
            <div
              role="row"
              key={row.task}
              className="grid items-baseline"
              style={{ gridTemplateColumns: "1fr 1.6fr 0.6fr", padding: "10px 0" }}
            >
              <span role="rowheader" className="text-[var(--ink)]">
                {row.task}
              </span>
              <span className="min-w-0">
                {row.onDevice ? <span className="text-[var(--ink)]">on-device</span> : <AttemptChain row={row} />}
              </span>
              <span className="text-right text-[var(--ink-secondary)]">
                {row.budgetMs === null ? "—" : `${row.budgetMs} ms`}
              </span>
            </div>
          ))}
          {killSwitchEngaged && (
            <p className="m-0 pt-[var(--space-2)] text-[var(--grey-600)]" style={{ fontSize: 11 }}>
              Cloud AI is paused — cloud routes above are refused. Local Ollama still works.
            </p>
          )}
        </div>
      )}
    </SettingsGroupCard>
  );
}
