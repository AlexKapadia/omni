/**
 * Rolling live summary panel — left column header above the notepad.
 */
import { SectionLabel } from "../section-label";
import { useLiveSummary } from "../../lib/live-summary-store";

export function LiveSummaryPanel() {
  const summaryMd = useLiveSummary((s) => s.summaryMd);
  if (summaryMd.length === 0) return null;

  return (
    <section
      aria-label="Rolling summary"
      className="border-b border-[var(--grey-200)] bg-[var(--wash-surface)]"
      style={{ padding: "12px 20px" }}
    >
      <SectionLabel>Summary so far</SectionLabel>
      <div
        className="mt-[var(--space-2)] whitespace-pre-wrap font-[family-name:var(--font-mono)] text-[var(--ink-secondary)]"
        style={{ fontSize: 12, lineHeight: 1.5 }}
      >
        {summaryMd}
      </div>
    </section>
  );
}
