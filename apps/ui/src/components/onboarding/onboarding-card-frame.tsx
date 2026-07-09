/**
 * The onboarding card shell — a 560px wide card. The required path is five steps
 * (welcome → features tour → speaker identity → notes folder → local models).
 * Step 6 is optional setup.
 * Content scrolls inside the card if a step is tall, so the card footprint stays constant.
 */
import type { ReactNode } from "react";

const TOTAL_STEPS = 6;

export function OnboardingCardFrame({
  step,
  children,
  footer,
}: {
  readonly step: 1 | 2 | 3 | 4 | 5 | 6;
  readonly children: ReactNode;
  readonly footer?: ReactNode;
}) {
  return (
    <section
      aria-label={`Onboarding step ${step} of ${TOTAL_STEPS}`}
      className="flex flex-col border border-[var(--grey-200)] bg-[var(--canvas)]"
      style={{
        width: 560,
        minHeight: 560,
        borderRadius: "var(--radius-card)",
        boxShadow: "var(--shadow-float)",
        padding: "32px 40px 24px",
      }}
    >
      {/* Segmented Progress Bar */}
      <div className="mb-6 flex gap-1.5 animate-fade-in" aria-hidden="true">
        {Array.from({ length: TOTAL_STEPS }).map((_, index) => {
          const isActive = index + 1 <= step;
          return (
            <div
              key={index}
              className="h-1 flex-1 rounded-sm transition-all duration-[var(--dur-page)]"
              style={{
                backgroundColor: isActive ? "var(--accent)" : "var(--grey-200)",
              }}
            />
          );
        })}
      </div>

      {/* Content Area */}
      <div className="flex min-h-0 flex-1 flex-col overflow-y-auto mb-[var(--space-6)]">
        {children}
      </div>

      {/* Footer Area */}
      {footer && (
        <div className="mt-auto pt-[var(--space-4)] border-t border-[var(--grey-200)]">
          {footer}
        </div>
      )}
    </section>
  );
}

