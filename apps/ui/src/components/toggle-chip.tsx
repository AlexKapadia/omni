/**
 * Labeled toggle chip for the Live capability strip (redesign-brief-v2.md
 * §5.3: "Notes · Summary · Answers · Translate · Captions · Board" — each a
 * toggle chip that shows/hides its panel). A real toggle button, not a
 * decoration: aria-pressed carries the on/off state for assistive tech,
 * never colour alone.
 *
 * Contrast (verified 2026-07-08): off-state text (--ink-secondary on
 * --surface) is 5.55:1; on-state text (--accent on --accent-muted) is
 * 5.88:1 — both comfortably clear the >=3:1 floor this component commits to
 * (and the >=4.5:1 AA text gate besides).
 */
import type { LucideIcon } from "lucide-react";

interface ToggleChipProps {
  readonly pressed: boolean;
  readonly onPressedChange: (next: boolean) => void;
  readonly label: string;
  // The chip's own accessible name is the text label, so the icon is always
  // decorative — aria-hidden is part of the prop contract, not optional.
  readonly icon?: LucideIcon;
  readonly disabled?: boolean;
}

export function ToggleChip({ pressed, onPressedChange, label, icon: Icon, disabled = false }: ToggleChipProps) {
  return (
    <button
      type="button"
      aria-pressed={pressed}
      disabled={disabled}
      onClick={() => onPressedChange(!pressed)}
      className={
        "inline-flex cursor-pointer items-center gap-[var(--space-2)] border font-[family-name:var(--font-body)] outline-none transition-colors disabled:cursor-default disabled:opacity-50 focus-visible:outline focus-visible:outline-2 focus-visible:outline-[var(--focus-ring)] focus-visible:outline-offset-2 " +
        (pressed
          ? "bg-[var(--accent-muted)] border-[var(--accent-border)] text-[var(--accent)]"
          : "bg-[var(--surface)] border-[var(--border-strong)] text-[var(--ink-secondary)] hover:border-[var(--grey-600)] hover:text-[var(--ink)]")
      }
      style={{
        borderRadius: "var(--radius-pill)",
        padding: "6px 12px",
        fontSize: 13,
        lineHeight: 1.4,
        transitionDuration: "var(--dur-micro)",
        transitionTimingFunction: "var(--ease-out)",
      }}
    >
      {Icon && <Icon aria-hidden size={14} className="shrink-0" />}
      <span>{label}</span>
    </button>
  );
}
