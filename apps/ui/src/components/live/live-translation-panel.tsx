/**
 * Rolling live translation — a collapsible left-column drawer (default
 * collapsed for a transcript-forward default). Translated lines stay mono
 * (evidence layer). Renders nothing until a translated line exists.
 */
import { CollapsibleDrawer } from "./collapsible-drawer";
import { useLiveTranslation } from "../../lib/live-translation-store";

export function LiveTranslationPanel() {
  const lines = useLiveTranslation((s) => s.lines);
  if (lines.length === 0) return null;

  return (
    <CollapsibleDrawer title="Translation">
      <div
        className="flex flex-col gap-[var(--space-1)] bg-[var(--wash-surface)]"
        style={{ padding: "0 20px 12px" }}
      >
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
    </CollapsibleDrawer>
  );
}
