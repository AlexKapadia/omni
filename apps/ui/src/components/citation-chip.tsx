/**
 * Source-citation chip for Ask Omni: renders the exact citation target
 * (note_path + line range, per the M3 §Cite contract) and toggles an inline
 * source detail (heading breadcrumb + verbatim snippet).
 *
 * Design (components doc §06): sources block sits above a hairline, mono 12
 * grey-600, hovering to ink. Opening a note in Obsidian is an M3+ action;
 * until then the chip's real behaviour is revealing its exact source.
 */
import type { AskCitation } from "../lib/ask-store";

export function CitationChip({
  citation,
  open,
  onToggle,
}: {
  readonly citation: AskCitation;
  readonly open: boolean;
  readonly onToggle: () => void;
}) {
  const lineRange = `L${citation.lineStart}–${citation.lineEnd}`;
  return (
    <div className="flex flex-col gap-[var(--space-1)]">
      <button
        type="button"
        onClick={onToggle}
        aria-expanded={open}
        // The accessible name IS the exact citation target — path + lines.
        aria-label={`${citation.notePath} · ${lineRange}`}
        className="cursor-pointer self-start border-none bg-transparent p-0 text-left font-[family-name:var(--font-mono)] text-[var(--grey-600)] hover:text-[var(--ink)]"
        style={{ fontSize: "var(--text-meta-size)", lineHeight: "var(--text-meta-lh)" }}
      >
        [{citation.marker}] {citation.notePath} · {lineRange}
      </button>
      {open && (
        <div
          className="border-l-2 border-[var(--grey-200)] font-[family-name:var(--font-mono)] text-[var(--ink-secondary)]"
          style={{ fontSize: 11, lineHeight: 1.6, paddingLeft: 20 }} // woven-context indent
        >
          <div>{citation.headingPath}</div>
          <div className="text-[var(--grey-600)]">“{citation.snippet}”</div>
        </div>
      )}
    </div>
  );
}
