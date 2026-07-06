/**
 * Left navigation rail (components doc §03): 224px, hairline right border,
 * the Omni lockup, one row per screen, and the on-device footer line.
 *
 * Sections are app state (no router dep — state-based routing in App.tsx).
 * The active indicator is a framer-motion shared-layout element; the Live
 * row carries the breathing ring while capture is genuinely live. Motion is
 * suppressed for users with prefers-reduced-motion.
 */
import { motion, useReducedMotion } from "framer-motion";
import { BreathingRing } from "./breathing-ring";
import { OmniMark } from "./omni-mark";
import { tokenDurationSeconds } from "../lib/design-token-motion";
import { useTranscript } from "../lib/transcript-store";

export type SectionId = "library" | "live" | "ask" | "naomi" | "settings";

const SECTIONS: ReadonlyArray<{ id: SectionId; label: string }> = [
  { id: "library", label: "Library" },
  { id: "live", label: "Live meeting" },
  { id: "ask", label: "Ask Omni" },
  { id: "naomi", label: "Naomi" },
  { id: "settings", label: "Settings" },
];

interface NavRailProps {
  readonly active: SectionId;
  readonly onSelect: (section: SectionId) => void;
}

export function NavRail({ active, onSelect }: NavRailProps) {
  const reducedMotion = useReducedMotion();
  const captureLive = useTranscript((s) => s.captureStatus === "live");

  return (
    <nav
      aria-label="Primary"
      className="flex shrink-0 flex-col border-r border-[var(--grey-200)]"
      style={{ width: 224, padding: "24px 16px" }} // doc: rail 224px, 24/16 padding
    >
      <div
        className="mb-[var(--space-8)] flex items-center px-[var(--space-3)]"
        style={{ gap: 10 }} // doc lockup gap
      >
        <OmniMark size={22} />
        <span
          className="font-[family-name:var(--font-display)] font-semibold text-[var(--ink)]"
          style={{ fontSize: 17, letterSpacing: "-0.02em" }} // doc: rail wordmark
        >
          Omni
        </span>
      </div>
      <ul className="m-0 flex list-none flex-col gap-[var(--space-1)] p-0">
        {SECTIONS.map((section) => {
          const isActive = section.id === active;
          return (
            <li key={section.id} className="relative">
              {isActive && (
                <motion.span
                  aria-hidden
                  layoutId="nav-active-indicator"
                  // Duration comes from the --dur-micro design token; zero when
                  // the user prefers reduced motion (accessibility contract).
                  transition={{
                    type: "tween",
                    duration: reducedMotion ? 0 : tokenDurationSeconds("--dur-micro"),
                  }}
                  className="absolute inset-0 rounded-[var(--radius-control)] bg-[var(--grey-50)]"
                />
              )}
              <button
                type="button"
                aria-current={isActive ? "page" : undefined}
                onClick={() => onSelect(section.id)}
                className={
                  "relative flex w-full cursor-pointer items-center justify-between border-none bg-transparent text-left " +
                  (isActive
                    ? "font-semibold text-[var(--ink)]"
                    : "text-[var(--grey-600)] hover:text-[var(--ink)]")
                }
                // Doc nav row: padding 9px 12px, 14px body size.
                style={{
                  padding: "9px 12px",
                  fontSize: "var(--text-body-size)",
                  borderRadius: "var(--radius-control)",
                }}
              >
                {section.label}
                {section.id === "live" && captureLive && <BreathingRing size={8} breathing />}
              </button>
            </li>
          );
        })}
      </ul>
      <div
        className="mt-auto border-t border-[var(--grey-200)]"
        style={{ padding: "16px 12px 0" }} // doc rail footer
      >
        <p className="m-0 text-[var(--grey-600)]" style={{ fontSize: "var(--text-meta-size)" }}>
          All data on this device
        </p>
      </div>
    </nav>
  );
}
