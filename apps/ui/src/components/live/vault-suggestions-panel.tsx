/**
 * Proactive vault suggestions — a floating, collapsible panel above the answers
 * panel. Follows the answers-panel affordance: an expanded card with a real
 * Collapse control, and a collapsed pill that expands again. Renders nothing
 * until the engine surfaces a real suggestion (honest idle).
 */
import { useState } from "react";
import { useVaultSuggestions } from "../../lib/vault-suggestions-store";

export function VaultSuggestionsPanel() {
  const suggestions = useVaultSuggestions((s) => s.suggestions);
  const [collapsed, setCollapsed] = useState(false);
  const latest = suggestions[0] ?? null;
  if (latest === null) return null;
  const top = latest.sources[0];
  if (top === undefined) return null;

  if (collapsed) {
    return (
      <button
        type="button"
        aria-label="Expand vault suggestion"
        onClick={() => setCollapsed(false)}
        className="absolute flex cursor-pointer items-center gap-[var(--space-2)] border-none bg-[var(--canvas)] text-[var(--grey-600)] outline-none hover:text-[var(--ink)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-[var(--focus-ring)]"
        style={{
          right: 20,
          bottom: 200,
          borderRadius: "var(--radius-pill)",
          padding: "8px 16px",
          fontSize: 13,
          boxShadow: "var(--shadow-float)",
        }}
      >
        From your vault · expand
      </button>
    );
  }

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
      <div className="flex items-baseline justify-between gap-[var(--space-2)]">
        <p
          className="m-0 font-[family-name:var(--font-mono)] text-[var(--ink-secondary)]"
          style={{ fontSize: 10, letterSpacing: "var(--label-ls)" }}
        >
          From your vault · {latest.latencyMs}ms
        </p>
        <button
          type="button"
          onClick={() => setCollapsed(true)}
          className="cursor-pointer border-none bg-transparent text-[var(--ink-secondary)] outline-none hover:text-[var(--ink)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-[var(--focus-ring)]"
          style={{ fontSize: "var(--text-meta-size)" }}
        >
          Collapse
        </button>
      </div>
      <p className="m-0 mt-1 text-[var(--ink)]" style={{ fontSize: 13, fontWeight: 600 }}>
        {latest.topic}
      </p>
      <p
        className="m-0 mt-2 font-[family-name:var(--font-mono)] text-[var(--ink-secondary)]"
        style={{ fontSize: 12, lineHeight: 1.45 }}
      >
        {top.snippet}
      </p>
      <p className="m-0 mt-1 text-[var(--ink-secondary)]" style={{ fontSize: 10 }}>
        {top.headingPath}
      </p>
    </aside>
  );
}
