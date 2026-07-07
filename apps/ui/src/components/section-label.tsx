/**
 * The universal section label: JetBrains Mono 11px, 0.08em tracking,
 * uppercase, ink-secondary (AA-compliant secondary text; was grey-400) —
 * "TRANSCRIPT", "AI ROUTER", "ANSWER" (brief §2).
 */
import type { ReactNode } from "react";

export function SectionLabel({ children }: { readonly children: ReactNode }) {
  return (
    <span
      className="font-[family-name:var(--font-mono)] uppercase text-[var(--ink-secondary)]"
      // 11px is the doc-pinned label size (no scale token exists for it).
      style={{ fontSize: 11, letterSpacing: "var(--label-ls)" }}
    >
      {children}
    </span>
  );
}
