/**
 * Onboarding step 1 — welcome + the privacy truths, stated plainly (design
 * §09). The aperture-animated mark plays "launch + onboarding only"; the copy
 * makes the local-only promises up front, before anything is set up.
 */
import { OmniButton } from "../button";
import { OmniMark } from "../omni-mark";

const PRIVACY_TRUTHS: readonly string[] = [
  "No bot joins your calls.",
  "Audio is captured on this machine only.",
  "Audio is discarded after transcription.",
];

export function StepWelcome({ onBegin }: { readonly onBegin: () => void }) {
  return (
    <div className="flex h-full flex-col items-center justify-center text-center">
      <span className="omni-aperture" aria-hidden>
        <OmniMark size={120} />
      </span>
      <h1
        className="mt-[var(--space-6)] mb-0 font-[family-name:var(--font-display)] font-semibold text-[var(--ink)]"
        style={{
          fontSize: "var(--text-page-size)",
          lineHeight: "var(--text-page-lh)",
          letterSpacing: "var(--text-page-ls)",
        }}
      >
        Omni
      </h1>
      <p
        className="mt-[var(--space-3)] mb-0 text-[var(--grey-600)]"
        style={{ fontSize: "var(--text-body-size)", maxWidth: 380 }}
      >
        Local-first meeting intelligence. It captures, transcribes, and enhances your notes on this
        device, and only ever drafts with your approval.
      </p>
      <ul className="mt-[var(--space-6)] mb-0 flex list-none flex-col gap-[var(--space-2)] p-0">
        {PRIVACY_TRUTHS.map((truth) => (
          <li
            key={truth}
            className="text-[var(--grey-600)]"
            style={{ fontSize: "var(--text-meta-size)" }}
          >
            {truth}
          </li>
        ))}
      </ul>
      <OmniButton
        variant="primary"
        onClick={onBegin}
        className="mt-[var(--space-8)]"
        style={{ padding: "12px 28px", fontSize: 15 }}
      >
        Begin
      </OmniButton>
    </div>
  );
}
