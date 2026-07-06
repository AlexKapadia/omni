/**
 * Left navigation rail: Meetings / Ask Omni / Settings.
 *
 * M0: sections are local state (no router yet — real routes arrive with real
 * screens). The active indicator is a framer-motion shared-layout element;
 * motion is suppressed for users with prefers-reduced-motion.
 */
import { motion, useReducedMotion } from "framer-motion";
import { tokenDurationSeconds } from "../lib/design-token-motion";

export type SectionId = "meetings" | "ask" | "settings";

const SECTIONS: ReadonlyArray<{ id: SectionId; label: string }> = [
  { id: "meetings", label: "Meetings" },
  { id: "ask", label: "Ask Omni" },
  { id: "settings", label: "Settings" },
];

interface NavRailProps {
  readonly active: SectionId;
  readonly onSelect: (section: SectionId) => void;
}

export function NavRail({ active, onSelect }: NavRailProps) {
  const reducedMotion = useReducedMotion();

  return (
    <nav
      aria-label="Primary"
      className="flex w-[200px] shrink-0 flex-col border-r border-[var(--grey-200)] px-[var(--space-3)] py-[var(--space-6)]"
    >
      <div className="mb-[var(--space-8)] px-[var(--space-3)] font-[family-name:var(--font-display)] text-lg tracking-tight">
        Omni
      </div>
      <ul className="flex flex-col gap-[var(--space-1)]">
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
                  "relative block w-full rounded-[var(--radius-control)] px-[var(--space-3)] py-[var(--space-2)] text-left text-sm " +
                  (isActive ? "text-[var(--ink)]" : "text-[var(--grey-600)] hover:text-[var(--ink)]")
                }
              >
                {section.label}
              </button>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
