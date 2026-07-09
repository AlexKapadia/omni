/**
 * Collapsible left-column drawer for the live meeting — keeps the default view
 * transcript-forward by folding the auxiliary panels (summary, translation,
 * notes) behind a real toggle. Follows the answers-panel pattern: framer-motion
 * for the reveal, gated to zero duration under prefers-reduced-motion so the
 * collapse animation never fights an accessibility preference.
 *
 * The header is a real <button> with aria-expanded so the collapse state is
 * announced; every interactive state (hover / focus-visible / open) is styled
 * from tokens — no raw hex, no dead affordance.
 */
import { motion, useReducedMotion } from "framer-motion";
import { useId, useState, type ReactNode } from "react";
import { SectionLabel } from "../section-label";
import { tokenDurationSeconds } from "../../lib/design-token-motion";

export function CollapsibleDrawer({
  title,
  defaultOpen = false,
  meta,
  children,
}: {
  readonly title: string;
  /** Auxiliary panels default closed (transcript-forward); primary ones open. */
  readonly defaultOpen?: boolean;
  /** Optional right-aligned meta (e.g. the meeting clock) shown in the header. */
  readonly meta?: ReactNode;
  readonly children: ReactNode;
}) {
  const [open, setOpen] = useState(defaultOpen);
  const reducedMotion = useReducedMotion();
  const panelId = useId();
  const seconds = reducedMotion ? 0 : tokenDurationSeconds("--dur-panel");

  return (
    <section aria-label={title} className="flex min-h-0 flex-col border-b border-[var(--grey-200)]">
      {/* Header row: the toggle button carries a STABLE accessible name (title
          only — no changing clock digits); any meta sits beside it, not inside. */}
      <div className="flex items-center" style={{ padding: "0 20px" }}>
        <button
          type="button"
          aria-expanded={open}
          aria-controls={panelId}
          onClick={() => setOpen((v) => !v)}
          className="flex flex-1 cursor-pointer items-center gap-[var(--space-2)] border-none bg-transparent text-left outline-none hover:bg-[var(--grey-50)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-[var(--focus-ring)]"
          style={{ padding: "10px 0", borderRadius: "var(--radius-control)" }}
        >
          <span
            aria-hidden="true"
            className="text-[var(--ink-secondary)]"
            style={{
              display: "inline-block",
              fontSize: 10,
              lineHeight: 1,
              transform: open ? "rotate(90deg)" : "rotate(0deg)",
              transition: reducedMotion ? undefined : "transform var(--dur-micro) var(--ease-out)",
            }}
          >
            ▶
          </span>
          <SectionLabel>{title}</SectionLabel>
        </button>
        {meta !== undefined && <span className="ml-[var(--space-3)]">{meta}</span>}
      </div>
      {/* Collapsing removes the content synchronously (no exit animation to get
          stuck on); the reveal fades/slides in, gated to zero under reduced
          motion. */}
      {open && (
        <motion.div
          id={panelId}
          initial={{ opacity: 0, y: -4 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: seconds, ease: [0, 0, 0.2, 1] }}
        >
          {children}
        </motion.div>
      )}
    </section>
  );
}
