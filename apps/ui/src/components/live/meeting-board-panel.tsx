/**
 * Meeting extraction board — structured actions, commitments, questions.
 */
import { SectionLabel } from "../section-label";

export interface ExtractionAction {
  readonly title: string;
  readonly owner?: string;
  readonly dueHint?: string;
}

export interface ExtractionCommitment {
  readonly who: string;
  readonly what: string;
  readonly when?: string;
}

export interface MeetingExtractionBoard {
  readonly actions: readonly ExtractionAction[];
  readonly commitments: readonly ExtractionCommitment[];
  readonly openQuestions: readonly string[];
  readonly contacts: readonly { readonly name: string }[];
}

function asString(value: unknown): string | null {
  return typeof value === "string" ? value : null;
}

export function parseMeetingExtraction(value: unknown): MeetingExtractionBoard | null {
  if (typeof value !== "object" || value === null) return null;
  const record = value as Record<string, unknown>;
  const actionsRaw = record["actions"];
  const commitmentsRaw = record["commitments"];
  const questionsRaw = record["open_questions"];
  const contactsRaw = record["contacts"];
  if (!Array.isArray(actionsRaw) || !Array.isArray(commitmentsRaw)) return null;
  if (!Array.isArray(questionsRaw) || !Array.isArray(contactsRaw)) return null;

  const actions: ExtractionAction[] = [];
  for (const item of actionsRaw) {
    if (typeof item !== "object" || item === null) return null;
    const row = item as Record<string, unknown>;
    const title = asString(row["title"]);
    if (title === null || title.length === 0) return null;
    actions.push({
      title,
      owner: asString(row["owner"]) ?? undefined,
      dueHint: asString(row["due_hint"]) ?? undefined,
    });
  }

  const commitments: ExtractionCommitment[] = [];
  for (const item of commitmentsRaw) {
    if (typeof item !== "object" || item === null) return null;
    const row = item as Record<string, unknown>;
    const who = asString(row["who"]);
    const what = asString(row["what"]);
    if (who === null || what === null) return null;
    commitments.push({ who, what, when: asString(row["when"]) ?? undefined });
  }

  const openQuestions: string[] = [];
  for (const q of questionsRaw) {
    if (typeof q !== "string") return null;
    openQuestions.push(q);
  }

  const contacts: { name: string }[] = [];
  for (const item of contactsRaw) {
    if (typeof item !== "object" || item === null) return null;
    const name = asString((item as Record<string, unknown>)["name"]);
    if (name === null) return null;
    contacts.push({ name });
  }

  return { actions, commitments, openQuestions, contacts };
}

export function MeetingBoardPanel({ extraction }: { readonly extraction: MeetingExtractionBoard }) {
  const hasContent =
    extraction.actions.length > 0 ||
    extraction.commitments.length > 0 ||
    extraction.openQuestions.length > 0;

  if (!hasContent) return null;

  return (
    <section aria-label="Meeting board" className="flex flex-col gap-[var(--space-2)]">
      <SectionLabel>Meeting board</SectionLabel>
      {extraction.actions.length > 0 && (
        <ul className="m-0 list-none p-0" style={{ fontSize: 13 }}>
          {extraction.actions.map((action) => (
            <li key={action.title} className="mb-1">
              ☐ {action.title}
              {action.owner !== undefined && (
                <span className="text-[var(--grey-600)]"> — {action.owner}</span>
              )}
            </li>
          ))}
        </ul>
      )}
      {extraction.commitments.length > 0 && (
        <ul className="m-0 mt-2 list-none p-0" style={{ fontSize: 13 }}>
          {extraction.commitments.map((c) => (
            <li key={`${c.who}-${c.what}`} className="mb-1">
              {c.who}: {c.what}
            </li>
          ))}
        </ul>
      )}
      {extraction.openQuestions.length > 0 && (
        <ul className="m-0 mt-2 list-none p-0 text-[var(--grey-600)]" style={{ fontSize: 13 }}>
          {extraction.openQuestions.map((q) => (
            <li key={q}>? {q}</li>
          ))}
        </ul>
      )}
    </section>
  );
}
