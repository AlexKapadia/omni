/**
 * Anchored, dismiss-once discovery card (redesign-brief-v2.md §5.2). Renders
 * a small floating card — title, body, "Got it" — next to an optional
 * anchor element, or inline if no anchor is given (e.g. a Home-screen
 * discover card that isn't pinned to a specific icon). Visibility is
 * entirely owned by useCoachmark()/coachmark-store.ts: at most one
 * coachmark is ever visible app-wide, and dismissal is permanent.
 *
 * a11y: never traps focus (no autoFocus, no tab cycling) and never blocks
 * input beyond its own footprint (only the card itself, not an oversized
 * wrapper, is positioned over the page — there is no backdrop). Escape
 * dismisses it while focus is anywhere inside the card.
 */
import type { ReactElement, ReactNode } from "react";
import { isValidElement, type HTMLAttributes, type KeyboardEvent } from "react";
import { AnimatePresence, motion, useReducedMotion } from "framer-motion";
import { tokenDurationSeconds } from "../lib/design-token-motion";
import { useCoachmark, coachmarkStore, type CoachmarkStore } from "../lib/coachmark-store";
import { OmniButton } from "./button";
import { copy } from "../lib/copy";
import type { TooltipSide } from "./tooltip";

interface CoachmarkProps {
  readonly id: string;
  readonly title: string;
  /** Body copy — plain text or short markup, rendered directly (a render-prop
   * would be overkill for a two-line discovery card). */
  readonly children: ReactNode;
  /** Element this coachmark floats beside. Omit for a card that renders
   * inline in normal document flow (no absolute positioning). */
  readonly anchor?: ReactElement<HTMLAttributes<HTMLElement>>;
  readonly side?: TooltipSide;
  /** Test/DI seam — defaults to the app singleton. */
  readonly store?: CoachmarkStore;
}

// Concrete keys only — avoid CSSProperties optionals under exactOptionalPropertyTypes.
const SIDE_OFFSET: Readonly<
  Record<TooltipSide, { readonly [key: string]: string | number }>
> = {
  top: { bottom: "100%", left: "50%", transform: "translateX(-50%)", marginBottom: 8 },
  bottom: { top: "100%", left: "50%", transform: "translateX(-50%)", marginTop: 8 },
  left: { right: "100%", top: "50%", transform: "translateY(-50%)", marginRight: 8 },
  right: { left: "100%", top: "50%", transform: "translateY(-50%)", marginLeft: 8 },
};

export function Coachmark({ id, title, children, anchor, side = "bottom", store = coachmarkStore }: CoachmarkProps) {
  const { visible, dismiss } = useCoachmark(id, store);
  const reducedMotion = useReducedMotion();

  if (anchor !== undefined && !isValidElement(anchor)) {
    throw new Error("Coachmark anchor must be a single element");
  }

  function handleKeyDown(e: KeyboardEvent<HTMLDivElement>) {
    if (e.key === "Escape") {
      e.stopPropagation(); // don't let Escape also close an ancestor modal/panel
      dismiss();
    }
  }

  // AnimatePresence must stay mounted continuously — only the child it
  // wraps toggles — otherwise it can never intercept the exit and animate
  // it (a conditionally-rendered AnimatePresence just unmounts instantly,
  // skipping the exit transition entirely).
  const cardWithPresence = (
    <AnimatePresence>
      {visible && (
        <motion.div
          role="dialog"
          aria-label={title}
          onKeyDown={handleKeyDown}
          initial={reducedMotion ? false : { opacity: 0, y: 4 }}
          animate={{ opacity: 1, y: 0 }}
          exit={reducedMotion ? { opacity: 0 } : { opacity: 0, y: 4 }}
          transition={{ duration: reducedMotion ? 0 : tokenDurationSeconds("--dur-panel") }}
          className={
            "flex flex-col gap-[var(--space-2)] bg-[var(--surface)] border border-[var(--grey-200)] shadow-[var(--shadow-float)] pointer-events-auto " +
            (anchor ? "absolute z-[var(--z-tooltip)]" : "relative")
          }
          style={{
            borderRadius: 14,
            maxWidth: 280,
            padding: 16,
            ...(anchor ? SIDE_OFFSET[side] : {}),
          }}
        >
          <p className="m-0 font-[family-name:var(--font-body)] font-semibold text-[var(--ink)]" style={{ fontSize: 14 }}>
            {title}
          </p>
          <p className="m-0 font-[family-name:var(--font-body)] text-[var(--ink-secondary)]" style={{ fontSize: 13, lineHeight: 1.5 }}>
            {children}
          </p>
          <div className="flex justify-end">
            <OmniButton variant="ghost" small onClick={dismiss}>
              {copy.common.gotIt}
            </OmniButton>
          </div>
        </motion.div>
      )}
    </AnimatePresence>
  );

  if (!anchor) {
    // No anchor: render inline, in normal document flow.
    return cardWithPresence;
  }

  return (
    <span style={{ position: "relative", display: "inline-flex" }}>
      {anchor}
      {cardWithPresence}
    </span>
  );
}
