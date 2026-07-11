import { useState, type FormEvent } from "react";
import { OmniButton } from "../button";
import { CitationChip } from "../citation-chip";
import { SkeletonShimmer } from "../skeleton-shimmer";
import { askAboutMeeting } from "../../lib/meeting-chat-repository";
import type { AskAnswer, AskProseSpan } from "../../lib/ask-store";

export function MeetingChatPanel({ meetingId }: { readonly meetingId: string }) {
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [answer, setAnswer] = useState<AskAnswer | null>(null);
  const [openMarker, setOpenMarker] = useState<number | null>(null);

  const submit = (event: FormEvent): void => {
    event.preventDefault();
    const query = draft.trim();
    if (query.length === 0 || busy) return;
    setBusy(true);
    setError(null);
    setOpenMarker(null);
    void askAboutMeeting(meetingId, query)
      .then((result) => {
        setAnswer(result);
      })
      .catch((err) => {
        setAnswer(null);
        setError(err instanceof Error ? err.message : "Could not get an answer.");
      })
      .finally(() => setBusy(false));
  };

  return (
    <div className="flex flex-col gap-[var(--space-3)]">
      <p className="m-0 text-[var(--grey-600)]" style={{ fontSize: 13 }}>
        Ask questions about this meeting only — transcript, your notes, and enhanced summary.
      </p>
      <form onSubmit={submit} className="flex flex-col gap-[var(--space-2)]">
        <input
          aria-label="Ask about this meeting"
          placeholder="What did we decide about the timeline?"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          className="w-full border border-[var(--grey-200)] bg-transparent px-3 py-2 text-[var(--ink)]"
          style={{ fontSize: 14 }}
        />
        <OmniButton variant="primary" small type="submit" disabled={busy}>
          {busy ? "Thinking…" : "Ask"}
        </OmniButton>
      </form>
      {busy && <SkeletonShimmer lines={3} />}
      {error !== null && (
        <p role="alert" className="m-0 text-[var(--grey-600)]" style={{ fontSize: 13 }}>
          {error}
        </p>
      )}
      {answer !== null && !busy && (
        <div className="flex flex-col gap-[var(--space-3)]">
          <h3 className="m-0 font-semibold text-[var(--ink)]" style={{ fontSize: 15 }}>
            {answer.headline}
          </h3>
          <p className="m-0 text-[var(--ink)]" style={{ fontSize: 14, lineHeight: 1.6 }}>
            {answer.prose.map((span: AskProseSpan, index: number) => (
              <span key={index} className={span.strong ? "font-semibold" : undefined}>
                {span.text}
                {span.citationMarker !== undefined && (
                  <sup className="font-[family-name:var(--font-mono)] text-[var(--accent)]">
                    [{span.citationMarker}]
                  </sup>
                )}
              </span>
            ))}
          </p>
          {answer.citations.length > 0 && (
            <div className="flex flex-col gap-[var(--space-2)] border-t border-[var(--grey-200)] pt-[var(--space-3)]">
              {answer.citations.map((citation) => (
                <CitationChip
                  key={citation.marker}
                  citation={citation}
                  open={openMarker === citation.marker}
                  onToggle={() =>
                    setOpenMarker((current) =>
                      current === citation.marker ? null : citation.marker,
                    )
                  }
                />
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
