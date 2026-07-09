/**
 * Live-meeting notepad — a collapsible left-column drawer (default OPEN: it is
 * the primary writing surface, but foldable so the transcript can take the full
 * view). Rough notes typed during capture are buffered in notepad-store so no
 * keystroke is lost on screen switches or when the drawer is collapsed.
 */
import { CollapsibleDrawer } from "./collapsible-drawer";
import { formatMeetingClock } from "../../lib/transcript-store";
import { notepadStore, setNotepadText, useNotepad } from "../../lib/notepad-store";

export function NotepadPane({
  meetingTitle,
  elapsedSeconds,
}: {
  readonly meetingTitle: string;
  readonly elapsedSeconds: number | null;
}) {
  const text = useNotepad((s) => s.text);

  return (
    <CollapsibleDrawer
      title={meetingTitle}
      defaultOpen
      meta={
        elapsedSeconds !== null ? (
          <span
            className="font-[family-name:var(--font-mono)] text-[var(--ink-secondary)]"
            style={{ fontSize: "var(--text-meta-size)" }}
          >
            {formatMeetingClock(elapsedSeconds)}
          </span>
        ) : undefined
      }
    >
      <div style={{ padding: "8px 24px 24px" }}>
        <textarea
          aria-label="Notepad"
          value={text}
          onChange={(event) => setNotepadText(notepadStore, event.target.value)}
          placeholder="Type anything. Omni Steroid is listening."
          spellCheck={false}
          className="w-full resize-none border-none bg-transparent text-[var(--ink)] outline-none placeholder:text-[var(--grey-300)]"
          // Note body 16px, line-height 2; a min height keeps it a real writing
          // surface even though the drawer sizes to its content.
          style={{
            fontFamily: "var(--font-body)",
            fontSize: "var(--text-emphasis-size)",
            lineHeight: 2,
            minHeight: 240,
          }}
        />
      </div>
    </CollapsibleDrawer>
  );
}
