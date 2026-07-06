/**
 * Empty state for each M0 placeholder section.
 *
 * Copy voice: sentence case, plain verbs, no exclamation marks. Real screens
 * replace these in later milestones; the copy is honest about that.
 */
import type { SectionId } from "./nav-rail";

const EMPTY_STATES: Readonly<Record<SectionId, { title: string; body: string }>> = {
  meetings: {
    title: "No meetings yet",
    body: "When Omni captures a meeting, it appears here with its transcript and notes.",
  },
  ask: {
    title: "Ask Omni",
    body: "Ask about your notes and past meetings. Available once the engine index is ready.",
  },
  settings: {
    title: "Settings",
    body: "Manage capture, providers, and keys here in a later milestone.",
  },
};

export function ViewEmptyState({ section }: { readonly section: SectionId }) {
  const copy = EMPTY_STATES[section];
  return (
    <section aria-label={copy.title} className="max-w-md px-[var(--space-8)] text-center">
      <h1 className="mb-[var(--space-2)] font-[family-name:var(--font-display)] text-xl text-[var(--ink)]">
        {copy.title}
      </h1>
      <p className="text-sm leading-relaxed text-[var(--grey-600)]">{copy.body}</p>
    </section>
  );
}
