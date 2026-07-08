/**
 * Rolling live translation panel — shows translated transcript lines.
 */
import { SectionLabel } from "../section-label";
import { useLiveTranslation } from "../../lib/live-translation-store";

export function LiveTranslationPanel() {
  const lines = useLiveTranslation((s) => s.lines);
  if (lines.length === 0) return null;

  return (
    <section
      aria-label="Live translation"
      className="border-b border-[var(--grey-200)] bg-[var(--wash-surface)]"
      style={{ padding: "12px 20px" }}
    >
      <SectionLabel>Translation</SectionLabel>
      <div className="mt-[var(--space-2)] flex flex-col gap-[var(--space-1)]">
        {lines.map((line, index) => (
          <div
            key={`${line.stream}-${index}`}
            className="font-[family-name:var(--font-mono)] text-[var(--ink-secondary)]"
            style={{ fontSize: 12, lineHeight: 1.5 }}
          >
            <span className="text-[var(--ink)]">{line.stream === "me" ? "Me" : "Them"}:</span>{" "}
            {line.text}
          </div>
        ))}
      </div>
    </section>
  );
}
