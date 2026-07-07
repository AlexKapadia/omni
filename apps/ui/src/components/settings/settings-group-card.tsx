/**
 * Settings primitives (components doc §10): a labelled group card
 * (grey-200 hairline, card radius, 6px 20px padding) whose rows are
 * 14px labels over hairline dividers, values right-aligned; two-line rows
 * carry a 12px ink-secondary sub-caption (AA-compliant; was grey-400).
 */
import type { ReactNode } from "react";
import { SectionLabel } from "../section-label";

export function SettingsGroupCard({
  label,
  children,
}: {
  readonly label: string;
  readonly children: ReactNode;
}) {
  return (
    <section aria-label={label} className="flex flex-col gap-[var(--space-2)]">
      <SectionLabel>{label}</SectionLabel>
      <div
        className="border border-[var(--grey-200)]"
        style={{ borderRadius: "var(--radius-card)", padding: "6px 20px" }}
      >
        {children}
      </div>
    </section>
  );
}

export function SettingsRow({
  title,
  subCaption,
  children,
  last = false,
}: {
  readonly title: string;
  readonly subCaption?: string;
  readonly children?: ReactNode;
  readonly last?: boolean;
}) {
  return (
    <div
      className={`flex items-center justify-between gap-[var(--space-4)] ${last ? "" : "border-b border-[var(--grey-200)]"}`}
      style={{ padding: "14px 0" }}
    >
      <div className="flex min-w-0 flex-col gap-[var(--space-1)]">
        <span className="text-[var(--ink)]" style={{ fontSize: "var(--text-body-size)" }}>
          {title}
        </span>
        {subCaption !== undefined && (
          <span className="text-[var(--ink-secondary)]" style={{ fontSize: "var(--text-meta-size)" }}>
            {subCaption}
          </span>
        )}
      </div>
      {children}
    </div>
  );
}
