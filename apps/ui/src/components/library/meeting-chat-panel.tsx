import { useState, type FormEvent } from "react";
import { OmniButton } from "../button";
import { SkeletonShimmer } from "../skeleton-shimmer";
import { askAboutMeeting } from "../../lib/meeting-chat-repository";
import type { AskProseSpan } from "../../lib/ask-store";

export function MeetingChatPanel({ meetingId }: { readonly meetingId: string }) {
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [headline, setHeadline] = useState<string | null>(null);
  const [prose, setProse] = useState<readonly AskProseSpan[] | null>(null);

  const submit = (event: FormEvent): void => {
    event.preventDefault();
    const query = draft.trim();
    if (query.length === 0 || busy) return;
    setBusy(true);
    setError(null);
    void askAboutMeeting(meetingId, query)
      .then((result) => {
        setHeadline(result.headline);
        setProse(result.prose);
      })
      .catch((err) => {
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
      {headline !== null && prose !== null && !busy && (
        <div>
          <h3 className="m-0 font-semibold text-[var(--ink)]" style={{ fontSize: 15 }}>
            {headline}
          </h3>
          <p className="m-0 mt-[var(--space-2)] text-[var(--ink)]" style={{ fontSize: 14, lineHeight: 1.6 }}>
            {prose.map((span, index) => (
              <span key={index} className={span.strong ? "font-semibold" : undefined}>
                {span.text}
              </span>
            ))}
          </p>
        </div>
      )}
    </div>
  );
}
