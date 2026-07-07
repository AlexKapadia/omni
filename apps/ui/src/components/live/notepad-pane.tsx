/**
 * Live-meeting notepad (left pane, flex:2): the user's rough notes, typed
 * during capture and buffered in notepad-store so no keystroke is lost on
 * screen switches. Body is 16px / line-height 2 per the components doc;
 * placeholder ghost copy is the doc's own line.
 */
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
    <section
      aria-label="Meeting notes"
      className="flex min-w-0 flex-col"
      // Doc: notepad flex:2, padding 56px 72px.
      style={{ flex: 2, padding: "56px 72px" }}
    >
      <div className="flex items-baseline justify-between gap-[var(--space-4)]">
        <h1
          className="m-0 font-[family-name:var(--font-display)] font-semibold text-[var(--ink)]"
          style={{
            fontSize: "var(--text-title-size)",
            lineHeight: "var(--text-title-lh)",
            letterSpacing: "var(--text-title-ls)",
          }}
        >
          {meetingTitle}
        </h1>
        {elapsedSeconds !== null && (
          <span
            className="font-[family-name:var(--font-mono)] text-[var(--ink-secondary)]"
            style={{ fontSize: "var(--text-meta-size)" }}
          >
            {formatMeetingClock(elapsedSeconds)}
          </span>
        )}
      </div>
      <textarea
        aria-label="Notepad"
        value={text}
        onChange={(event) => setNotepadText(notepadStore, event.target.value)}
        placeholder="Type anything. Omni is listening."
        spellCheck={false}
        className="mt-[var(--space-6)] w-full flex-1 resize-none border-none bg-transparent text-[var(--ink)] outline-none placeholder:text-[var(--grey-300)]"
        // Doc: note body 16px, line-height 2.
        style={{
          fontFamily: "var(--font-body)",
          fontSize: "var(--text-emphasis-size)",
          lineHeight: 2,
        }}
      />
    </section>
  );
}
