/**
 * Meeting detail pane — opened from a Library row, rendered inside the
 * Library screen as a right-hand panel.
 *
 * Shows the three layers of one captured meeting: Enhanced Notes (engine
 * markdown through the XSS-safe renderer), My Notes (the user's rough notes,
 * verbatim, plain text), and the transcript in a collapsed disclosure. An
 * ended-but-unfinalized meeting gets a working "Enhance now" action that
 * sends meeting.finalize with the notepad buffer (when it belongs to this
 * meeting). States: loading shimmer, error + retry, ready — none faked.
 */
import { useCallback, useEffect } from "react";
import { ApprovalRack } from "../components/approval/approval-rack";
import { OmniButton } from "../components/button";
import { SectionLabel } from "../components/section-label";
import { SkeletonShimmer } from "../components/skeleton-shimmer";
import { formatClockShort, formatDayLabel, formatDurationMin } from "../lib/format-quantities";
import type { FinalizeOutcome, MeetingDetail } from "../lib/meetings-live-repository";
import { SafeMarkdown } from "../lib/meetings-safe-markdown";
import {
  closeMeetingDetail,
  loadMeetingDetail,
  meetingsDetailStore,
  runMeetingFinalize,
  useMeetingsDetail,
} from "../lib/meetings-detail-store";
import { useNotepad } from "../lib/notepad-store";

export type DetailLoader = (meetingId: string) => Promise<MeetingDetail>;
export type MeetingFinalizer = (
  meetingId: string,
  notepadText: string,
) => Promise<FinalizeOutcome>;

function PaneSection({ label, children }: { readonly label: string; readonly children: React.ReactNode }) {
  return (
    <section aria-label={label} className="flex flex-col gap-[var(--space-2)]">
      <SectionLabel>{label}</SectionLabel>
      <div className="text-[var(--ink)]" style={{ fontSize: "var(--text-body-size)" }}>
        {children}
      </div>
    </section>
  );
}

export function LibraryMeetingDetailPane({
  meetingId,
  loadDetail,
  finalizeMeeting,
  onFinalized,
}: {
  readonly meetingId: string;
  readonly loadDetail: DetailLoader;
  readonly finalizeMeeting: MeetingFinalizer;
  /** Called after a successful finalize so the list can refresh. */
  readonly onFinalized: () => void;
}) {
  const status = useMeetingsDetail((s) => s.status);
  const detail = useMeetingsDetail((s) => s.detail);
  const errorMessage = useMeetingsDetail((s) => s.errorMessage);
  const finalizing = useMeetingsDetail((s) => s.finalizing);
  const finalizeMessage = useMeetingsDetail((s) => s.finalizeMessage);
  const notepadMeetingId = useNotepad((s) => s.meetingId);
  const notepadText = useNotepad((s) => s.text);

  const load = useCallback(
    () => void loadMeetingDetail(meetingsDetailStore, loadDetail, meetingId),
    [loadDetail, meetingId],
  );
  useEffect(load, [load]);

  const canFinalize =
    detail !== null && !detail.finalized && detail.endedIso !== null && !finalizing;
  // The notepad buffer only belongs to this meeting if the ids match —
  // never send another meeting's notes (fidelity + information boundary).
  const notepadForThisMeeting = notepadMeetingId === meetingId ? notepadText : "";

  return (
    <aside
      aria-label="Meeting detail"
      className="flex h-full flex-col gap-[var(--space-5)] overflow-y-auto border-l border-[var(--grey-200)]"
      style={{ width: 420, flexShrink: 0, padding: "48px 32px" }}
    >
      <header className="flex items-start justify-between gap-[var(--space-3)]">
        <div className="flex min-w-0 flex-col gap-[var(--space-1)]">
          <h2
            className="m-0 font-[family-name:var(--font-display)] font-semibold text-[var(--ink)]"
            style={{ fontSize: "var(--text-section-size)", letterSpacing: "var(--text-section-ls)" }}
          >
            {detail?.title ?? "Meeting"}
          </h2>
          {detail !== null && (
            <span
              className="font-[family-name:var(--font-mono)] text-[var(--ink-secondary)]"
              style={{ fontSize: "var(--text-meta-size)" }}
            >
              {formatDayLabel(detail.startIso)} · {formatClockShort(detail.startIso)}
              {detail.endedIso !== null && ` · ${formatDurationMin(detail.durationMin)}`}
            </span>
          )}
        </div>
        <OmniButton
          variant="secondary"
          small
          aria-label="Close meeting detail"
          onClick={() => closeMeetingDetail(meetingsDetailStore)}
        >
          Close
        </OmniButton>
      </header>

      {status === "loading" && <SkeletonShimmer lines={6} />}

      {status === "error" && (
        <div className="flex flex-col items-start gap-[var(--space-3)]">
          <p className="m-0 text-[var(--ink)]" style={{ fontSize: "var(--text-body-size)" }}>
            Could not load this meeting.
          </p>
          <p className="m-0 text-[var(--grey-600)]" style={{ fontSize: 13 }}>
            {errorMessage}
          </p>
          <OmniButton variant="secondary" onClick={load}>
            Retry loading
          </OmniButton>
        </div>
      )}

      {status === "ready" && detail !== null && (
        <>
          <PaneSection label="Enhanced Notes">
            {detail.enhancedNotesMd.length > 0 ? (
              <SafeMarkdown markdown={detail.enhancedNotesMd} />
            ) : (
              <p className="m-0 text-[var(--grey-600)]">
                {detail.finalized
                  ? "Enhancement was unavailable for this meeting — your notes and transcript below are intact."
                  : "Not enhanced yet."}
              </p>
            )}
            {canFinalize && (
              <div className="mt-[var(--space-3)]">
                <OmniButton
                  variant="primary"
                  small
                  onClick={() =>
                    void runMeetingFinalize(
                      meetingsDetailStore,
                      finalizeMeeting,
                      loadDetail,
                      meetingId,
                      notepadForThisMeeting,
                      onFinalized,
                    )
                  }
                >
                  Enhance now
                </OmniButton>
              </div>
            )}
            {finalizing && (
              <p className="m-0 mt-[var(--space-2)] text-[var(--grey-600)]" style={{ fontSize: 13 }}>
                Enhancing — fusing your notes with the transcript…
              </p>
            )}
            {finalizeMessage !== null && (
              <p role="status" className="m-0 mt-[var(--space-2)] text-[var(--grey-600)]" style={{ fontSize: 13 }}>
                {finalizeMessage}
              </p>
            )}
          </PaneSection>

          <PaneSection label="Suggested Actions">
            {/* The M4 approval rack, scoped to this meeting's extraction
                cards. All states are the rack's own honest ones (loading /
                empty / engine offline / the cards themselves). */}
            <ApprovalRack meetingId={meetingId} />
          </PaneSection>

          <PaneSection label="My Notes">
            {detail.notesText.length > 0 || notepadForThisMeeting.length > 0 ? (
              // Verbatim, plain text (fidelity mandate): pre-wrap preserves
              // the user's own line structure exactly, no markdown parsing.
              <pre
                className="m-0 whitespace-pre-wrap font-[family-name:var(--font-body,inherit)]"
                style={{ fontSize: "var(--text-body-size)", lineHeight: "var(--text-body-lh)" }}
              >
                {detail.notesText.length > 0 ? detail.notesText : notepadForThisMeeting}
              </pre>
            ) : (
              <p className="m-0 text-[var(--grey-600)]">No notes were typed for this meeting.</p>
            )}
          </PaneSection>

          <PaneSection label="Transcript">
            {detail.transcript.length === 0 ? (
              <p className="m-0 text-[var(--grey-600)]">No transcript was captured.</p>
            ) : (
              <details>
                <summary
                  className="cursor-pointer text-[var(--grey-600)]"
                  style={{ fontSize: "var(--text-body-size)" }}
                >
                  {detail.transcript.length} segments — click to expand
                </summary>
                <ul className="m-0 mt-[var(--space-2)] flex list-none flex-col gap-[var(--space-1)] p-0">
                  {detail.transcript.map((line, index) => (
                    <li key={index} style={{ fontSize: 13, lineHeight: "1.5" }}>
                      <span className="font-[family-name:var(--font-mono)] text-[var(--ink-secondary)]">
                        {line.stream === "me" ? "Me" : "Them"}:
                      </span>{" "}
                      <span className="text-[var(--ink)]">{line.text}</span>
                    </li>
                  ))}
                </ul>
              </details>
            )}
          </PaneSection>
        </>
      )}
    </aside>
  );
}
