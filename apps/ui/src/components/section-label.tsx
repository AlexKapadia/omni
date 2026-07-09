/**
 * The universal section label. Rehaul v2 (Evidence Mono Rule): section labels
 * are Inter 500 sentence case — NOT mono uppercase eyebrows. Mono is reserved
 * for transcript/code/ledger evidence. Renders the label text as passed
 * (sentence case), so callers own the casing. ink-secondary keeps it AA.
 */
import type { ReactNode } from "react";

export function SectionLabel({ children }: { readonly children: ReactNode }) {
  return (
    <span
      className="font-[family-name:var(--font-label)] font-medium text-[var(--ink-secondary)]"
      style={{ fontSize: 13, lineHeight: 1.4 }}
    >
      {children}
    </span>
  );
}
