/**
 * Rolling live summary — a collapsible left-column drawer (default collapsed to
 * keep the live view transcript-forward). Renders nothing until the engine has
 * emitted a rolling summary, so the drawer never shows an empty shell.
 */
import { CollapsibleDrawer } from "./collapsible-drawer";
import { useLiveSummary } from "../../lib/live-summary-store";

export function LiveSummaryPanel() {
  const summaryMd = useLiveSummary((s) => s.summaryMd);
  if (summaryMd.length === 0) return null;

  return (
    <CollapsibleDrawer title="Summary so far">
      <div
        className="whitespace-pre-wrap bg-[var(--wash-surface)] font-[family-name:var(--font-mono)] text-[var(--ink-secondary)]"
        style={{ fontSize: 12, lineHeight: 1.5, padding: "0 20px 12px" }}
      >
        {summaryMd}
      </div>
    </CollapsibleDrawer>
  );
}
