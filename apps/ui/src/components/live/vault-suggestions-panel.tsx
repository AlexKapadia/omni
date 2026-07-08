/**
 * Proactive vault suggestions — floating panel above the answers panel.
 */
import { useVaultSuggestions } from "../../lib/vault-suggestions-store";

export function VaultSuggestionsPanel() {
  const suggestions = useVaultSuggestions((s) => s.suggestions);
  const latest = suggestions[0] ?? null;
  if (latest === null) return null;
  const top = latest.sources[0];
  if (top === undefined) return null;

  return (
    <aside
      aria-label="Vault suggestion"
      className="absolute border border-[var(--grey-200)] bg-[var(--canvas)]"
      style={{
        right: 20,
        bottom: 200,
        width: 320,
        borderRadius: 12,
        padding: "12px 16px",
        boxShadow: "var(--shadow-float)",
      }}
    >
      <p
        className="m-0 font-[family-name:var(--font-mono)] text-[var(--ink-secondary)]"
        style={{ fontSize: 10, letterSpacing: "var(--label-ls)" }}
      >
        From your vault · {latest.latencyMs}ms
      </p>
      <p className="m-0 mt-1 text-[var(--ink)]" style={{ fontSize: 13, fontWeight: 600 }}>
        {latest.topic}
      </p>
      <p
        className="m-0 mt-2 font-[family-name:var(--font-mono)] text-[var(--ink-secondary)]"
        style={{ fontSize: 12, lineHeight: 1.45 }}
      >
        {top.snippet}
      </p>
      <p className="m-0 mt-1 text-[var(--grey-500)]" style={{ fontSize: 10 }}>
        {top.headingPath}
      </p>
    </aside>
  );
}
