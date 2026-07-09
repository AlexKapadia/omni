import { useState } from "react";
import { OmniButton } from "../button";
import {
  replaceMeetingText,
  type TextReplaceTarget,
} from "../../lib/meeting-text-replace-repository";

export function MeetingSearchReplacePanel({
  meetingId,
  onReplaced,
}: {
  readonly meetingId: string;
  readonly onReplaced: () => void;
}) {
  const [find, setFind] = useState("");
  const [replace, setReplace] = useState("");
  const [target, setTarget] = useState<TextReplaceTarget>("both");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  const run = async (): Promise<void> => {
    const trimmed = find.trim();
    if (trimmed.length === 0) {
      setMessage("Enter text to find.");
      return;
    }
    setBusy(true);
    setMessage(null);
    try {
      const result = await replaceMeetingText(meetingId, trimmed, replace, target);
      const total = result.transcriptSegments + result.enhancedNotes;
      setMessage(
        total > 0
          ? `Replaced in ${result.transcriptSegments} segment(s) and ${result.enhancedNotes} note section(s).`
          : "No matches found.",
      );
      if (total > 0) onReplaced();
    } catch (err) {
      setMessage(err instanceof Error ? err.message : "Replace failed.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="flex flex-col gap-[var(--space-2)]">
      <label className="text-[var(--ink-secondary)]" style={{ fontSize: 12 }}>
        Find
        <input
          className="mt-[var(--space-1)] block w-full border border-[var(--grey-200)] px-2 py-1"
          style={{ fontSize: 13 }}
          value={find}
          onChange={(e) => setFind(e.target.value)}
        />
      </label>
      <label className="text-[var(--ink-secondary)]" style={{ fontSize: 12 }}>
        Replace with
        <input
          className="mt-[var(--space-1)] block w-full border border-[var(--grey-200)] px-2 py-1"
          style={{ fontSize: 13 }}
          value={replace}
          onChange={(e) => setReplace(e.target.value)}
        />
      </label>
      <label className="text-[var(--ink-secondary)]" style={{ fontSize: 12 }}>
        In
        <select
          className="mt-[var(--space-1)] block w-full border border-[var(--grey-200)] bg-transparent px-2 py-1"
          style={{ fontSize: 13 }}
          value={target}
          onChange={(e) => setTarget(e.target.value as TextReplaceTarget)}
        >
          <option value="both">Transcript and enhanced notes</option>
          <option value="transcript">Transcript only</option>
          <option value="enhanced_notes">Enhanced notes only</option>
        </select>
      </label>
      <OmniButton variant="secondary" small disabled={busy} onClick={() => void run()}>
        {busy ? "Replacing…" : "Replace all"}
      </OmniButton>
      {message !== null && (
        <p role="status" className="m-0 text-[var(--grey-600)]" style={{ fontSize: 12 }}>
          {message}
        </p>
      )}
    </div>
  );
}
