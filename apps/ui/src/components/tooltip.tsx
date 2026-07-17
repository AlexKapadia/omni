/**
 * Lightweight anchored tooltip (redesign-brief-v2.md §5.2: "no icon-only
 * control without a tooltip"). Wraps exactly one focusable/hoverable child —
 * an icon button, typically — and shows a small anchored label on hover AND
 * on keyboard focus, so the contract holds for mouse and keyboard users
 * alike. No positioning library: placement is plain CSS anchored to a
 * relatively-positioned wrapper via the `side` prop.
 *
 * a11y: role="tooltip" + aria-describedby wired onto the child only while
 * visible (WAI-ARIA tooltip pattern), so screen readers never announce a
 * hidden node's id. A 300ms show delay avoids flashing a tooltip on every
 * incidental mouse pass; hide is immediate so it never lingers stale.
 */
import {
  cloneElement,
  isValidElement,
  useEffect,
  useId,
  useRef,
  useState,
  type FocusEvent,
  type HTMLAttributes,
  type MouseEvent,
  type ReactElement,
} from "react";
import { AnimatePresence, motion, useReducedMotion } from "framer-motion";
import { tokenDurationSeconds } from "../lib/design-token-motion";

const SHOW_DELAY_MS = 300; // WHY: matches common OS tooltip delay; short enough to feel responsive, long enough to not flash on cursor pass-through

export type TooltipSide = "top" | "bottom" | "left" | "right";

interface TooltipProps {
  readonly label: string;
  readonly children: ReactElement<HTMLAttributes<HTMLElement>>;
  readonly side?: TooltipSide;
}

// Anchors the floating label to the wrapper; no measurement/collision logic
// (out of scope for this lightweight primitive — see brief §5.2 "lightweight").
// Concrete keys only — avoid CSSProperties optionals under exactOptionalPropertyTypes.
const SIDE_OFFSET: Readonly<
  Record<TooltipSide, { readonly [key: string]: string | number }>
> = {
  top: { bottom: "100%", left: "50%", transform: "translateX(-50%)", marginBottom: 6 },
  bottom: { top: "100%", left: "50%", transform: "translateX(-50%)", marginTop: 6 },
  left: { right: "100%", top: "50%", transform: "translateY(-50%)", marginRight: 6 },
  right: { left: "100%", top: "50%", transform: "translateY(-50%)", marginLeft: 6 },
};

export function Tooltip({ label, children, side = "top" }: TooltipProps) {
  const [visible, setVisible] = useState(false);
  const showTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const tooltipId = useId();
  const reducedMotion = useReducedMotion();

  // Fail-safe: never leave a pending show timer running past unmount.
  useEffect(() => {
    return () => {
      if (showTimer.current !== null) clearTimeout(showTimer.current);
    };
  }, []);

  if (!isValidElement(children)) {
    // Defensive: this primitive only wraps a single element. Failing loudly
    // in development surfaces the bug immediately rather than silently
    // dropping the tooltip (which would violate the "no icon-only control
    // without a tooltip" contract without anyone noticing).
    throw new Error("Tooltip requires a single element child");
  }

  function scheduleShow() {
    if (showTimer.current !== null) clearTimeout(showTimer.current);
    showTimer.current = setTimeout(() => setVisible(true), SHOW_DELAY_MS);
  }

  function hide() {
    if (showTimer.current !== null) {
      clearTimeout(showTimer.current);
      showTimer.current = null;
    }
    setVisible(false);
  }

  const child = cloneElement(children, {
    "aria-describedby": visible ? tooltipId : undefined,
    onMouseEnter: (e: MouseEvent<HTMLElement>) => {
      children.props.onMouseEnter?.(e);
      scheduleShow();
    },
    onMouseLeave: (e: MouseEvent<HTMLElement>) => {
      children.props.onMouseLeave?.(e);
      hide();
    },
    onFocus: (e: FocusEvent<HTMLElement>) => {
      children.props.onFocus?.(e);
      scheduleShow();
    },
    onBlur: (e: FocusEvent<HTMLElement>) => {
      children.props.onBlur?.(e);
      hide();
    },
  } satisfies Partial<HTMLAttributes<HTMLElement>>);

  return (
    <span style={{ position: "relative", display: "inline-flex" }}>
      {child}
      <AnimatePresence>
        {visible && (
          <motion.span
            role="tooltip"
            id={tooltipId}
            initial={reducedMotion ? false : { opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: reducedMotion ? 0 : tokenDurationSeconds("--dur-panel") }}
            className="pointer-events-none whitespace-nowrap bg-[var(--ink)] text-[var(--canvas)] font-[family-name:var(--font-body)] z-[var(--z-tooltip)] shadow-[var(--shadow-float)]"
            style={{
              position: "absolute",
              borderRadius: 6,
              padding: "4px 8px",
              fontSize: 12,
              lineHeight: 1.4,
              ...SIDE_OFFSET[side],
            }}
          >
            {label}
          </motion.span>
        )}
      </AnimatePresence>
    </span>
  );
}
