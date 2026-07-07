/**
 * The onboarding card shell — a 560×560 white card with the step marker
 * "N / 4" (design §09, "a two-minute ritual"). Content scrolls inside the card
 * if a step is tall (the keys step), so the card footprint stays constant.
 */
import type { ReactNode } from "react";

export function OnboardingCardFrame({
  step,
  children,
}: {
  readonly step: 1 | 2 | 3 | 4;
  readonly children: ReactNode;
}) {
  return (
    <section
      aria-label={`Onboarding step ${step} of 4`}
      className="flex flex-col border border-[var(--grey-200)] bg-[var(--canvas)]"
      style={{
        width: 560,
        height: 560,
        borderRadius: "var(--radius-card)",
        boxShadow: "var(--shadow-float)",
        padding: "40px 40px 24px",
      }}
    >
      <div className="flex min-h-0 flex-1 flex-col overflow-y-auto">{children}</div>
      <p
        className="m-0 pt-[var(--space-4)] text-center font-[family-name:var(--font-mono)] text-[var(--ink-secondary)]"
        style={{ fontSize: 11, letterSpacing: "var(--label-ls)" }}
      >
        {step} / 4
      </p>
    </section>
  );
}
