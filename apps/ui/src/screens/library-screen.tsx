/**
 * Library — home screen: every captured meeting, newest first, grouped by
 * day, with a search filter that narrows as you type, and a detail pane
 * (enhanced notes / my notes / transcript) opened by clicking a row.
 *
 * Data flows from meetings-store through the MeetingsRepository interface —
 * the LIVE engine repository (meetings.list over WS) by default; tests
 * inject fakes. States: loading (shimmer, never a spinner), error (+ retry),
 * empty, and populated with a separate no-matches state for a live query.
 */
import { useEffect, useMemo } from "react";
import { OmniButton } from "../components/button";
import { SectionLabel } from "../components/section-label";
import { SkeletonShimmer } from "../components/skeleton-shimmer";
import {
  formatClockShort,
  formatDayLabel,
  formatDurationMin,
  formatStartsIn,
} from "../lib/format-quantities";
import { useEngineStatus } from "../lib/engine-status-store";
import {
  meetingsDetailStore,
  openMeetingDetail,
  useMeetingsDetail,
} from "../lib/meetings-detail-store";
import {
  createLiveMeetingsRepository,
  getMeetingDetail,
  requestMeetingFinalize,
} from "../lib/meetings-live-repository";
import {
  filterMeetings,
  loadMeetings,
  meetingsStore,
  setMeetingsQuery,
  useMeetings,
  type MeetingsRepository,
  type MeetingSummaryRow,
} from "../lib/meetings-store";
import {
  LibraryMeetingDetailPane,
  type DetailLoader,
  type MeetingFinalizer,
} from "./library-meeting-detail-pane";

/** LIVE engine repository (meetings.list over the WS protocol). */
const defaultRepository: MeetingsRepository = createLiveMeetingsRepository();
const defaultDetailLoader: DetailLoader = (id) => getMeetingDetail(id);
const defaultFinalizer: MeetingFinalizer = (id, notepad) => requestMeetingFinalize(id, notepad);

function MeetingRow({
  meeting,
  onOpen,
}: {
  readonly meeting: MeetingSummaryRow;
  readonly onOpen: (meetingId: string) => void;
}) {
  const startsIn = formatStartsIn(meeting.startIso);
  const upcoming = startsIn !== null;
  return (
    <li className="list-none">
      <button
        type="button"
        aria-label={`Open ${meeting.title}`}
        onClick={() => onOpen(meeting.id)}
        className="grid w-full cursor-pointer items-baseline border-0 border-t border-solid border-[var(--grey-200)] bg-transparent text-left hover:bg-[var(--grey-50)]"
        // Doc row spec: 88px | 1fr | 120px, gap 24, padding 18px 16px, -16px bleed.
        style={{
          gridTemplateColumns: "88px 1fr 120px",
          gap: "var(--space-6)",
          padding: "18px 16px",
          margin: "0 -16px",
          width: "calc(100% + 32px)",
          borderRadius: "var(--radius-control)",
        }}
      >
        <span
          className={`font-[family-name:var(--font-mono)] ${upcoming ? "text-[var(--ink)]" : "text-[var(--grey-400)]"}`}
          style={{ fontSize: "var(--text-meta-size)" }}
        >
          {formatClockShort(meeting.startIso)}
        </span>
        <span className="flex min-w-0 flex-col gap-[var(--space-1)]">
          <span className="truncate font-medium text-[var(--ink)]" style={{ fontSize: 15 }}>
            {meeting.title}
          </span>
          {meeting.summary.length > 0 && (
            <span className="truncate text-[var(--grey-400)]" style={{ fontSize: 13 }}>
              {meeting.summary}
            </span>
          )}
        </span>
        <span
          className={`text-right font-[family-name:var(--font-mono)] ${upcoming ? "text-[var(--grey-600)]" : "text-[var(--grey-400)]"}`}
          style={{ fontSize: "var(--text-meta-size)" }}
        >
          {upcoming ? startsIn : formatDurationMin(meeting.durationMin)}
        </span>
      </button>
    </li>
  );
}

export function LibraryScreen({
  repository = defaultRepository,
  detailLoader = defaultDetailLoader,
  finalizer = defaultFinalizer,
  onStartCapture,
}: {
  readonly repository?: MeetingsRepository;
  readonly detailLoader?: DetailLoader;
  readonly finalizer?: MeetingFinalizer;
  readonly onStartCapture: () => void;
}) {
  const status = useMeetings((s) => s.status);
  const meetings = useMeetings((s) => s.meetings);
  const query = useMeetings((s) => s.query);
  const errorMessage = useMeetings((s) => s.errorMessage);
  const selectedId = useMeetingsDetail((s) => s.selectedId);
  const engineStatus = useEngineStatus((s) => s.status);

  useEffect(() => {
    // Load once per app session (mount-only by design); the error state's
    // retry button re-triggers the load explicitly.
    const current = meetingsStore.getState();
    if (current.status === "loading" && current.meetings.length === 0) {
      void loadMeetings(meetingsStore, repository);
    }
  }, [repository]);

  useEffect(() => {
    // Cold-boot race recovery: the Library is the default screen, so it mounts
    // before the engine WebSocket has finished opening — the first meetings.list
    // then fails "offline" even though the engine is fine. When the connection
    // comes up, re-load once so the user never sees a false offline state and
    // never has to click Retry. Only re-loads out of the error state (a healthy
    // ready/loading state is left untouched — no redundant refetch).
    if (engineStatus === "connected" && meetingsStore.getState().status === "error") {
      void loadMeetings(meetingsStore, repository);
    }
  }, [engineStatus, repository]);

  const visible = useMemo(() => filterMeetings(meetings, query), [meetings, query]);
  const groups = useMemo(() => {
    const byDay = new Map<string, MeetingSummaryRow[]>();
    for (const meeting of visible) {
      const label = formatDayLabel(meeting.startIso);
      const bucket = byDay.get(label);
      if (bucket === undefined) byDay.set(label, [meeting]);
      else bucket.push(meeting);
    }
    return [...byDay.entries()];
  }, [visible]);

  const capturedMin = meetings.reduce((acc, m) => acc + m.durationMin, 0);
  const openDetail = (meetingId: string): void =>
    openMeetingDetail(meetingsDetailStore, meetingId);

  return (
    <div className="flex h-full">
      <div className="h-full flex-1 overflow-y-auto" style={{ padding: "48px 64px" }}>
      <header className="flex items-start justify-between gap-[var(--space-4)]">
        <div className="flex flex-col gap-[var(--space-2)]">
          <h1
            className="m-0 font-[family-name:var(--font-display)] font-semibold text-[var(--ink)]"
            style={{
              fontSize: "var(--text-title-size)",
              lineHeight: "var(--text-title-lh)",
              letterSpacing: "var(--text-title-ls)",
            }}
          >
            Library
          </h1>
          {status === "ready" && meetings.length > 0 && (
            <span
              className="font-[family-name:var(--font-mono)] text-[var(--grey-400)]"
              style={{ fontSize: "var(--text-meta-size)" }}
            >
              {meetings.length} meetings · {formatDurationMin(capturedMin)} captured · all on this device
            </span>
          )}
        </div>
        <OmniButton variant="primary" onClick={onStartCapture}>
          Start capture
        </OmniButton>
      </header>

      <div className="mt-[var(--space-6)]">
        <input
          type="search"
          aria-label="Search meetings"
          placeholder="Search meetings"
          value={query}
          onChange={(event) => setMeetingsQuery(meetingsStore, event.target.value)}
          className="border border-[var(--grey-300)] bg-transparent text-[var(--ink)] outline-none placeholder:text-[var(--grey-400)] focus:border-[var(--ink)]"
          style={{
            borderRadius: "var(--radius-control)",
            padding: "9px 14px",
            fontSize: "var(--text-body-size)",
            width: 240,
          }}
        />
      </div>

      <div className="mt-[var(--space-8)]">
        {status === "loading" && <SkeletonShimmer lines={4} />}

        {status === "error" && (
          <div className="flex max-w-md flex-col items-start gap-[var(--space-3)]">
            <p className="m-0 text-[var(--ink)]" style={{ fontSize: "var(--text-body-size)" }}>
              Could not load your meetings.
            </p>
            <p className="m-0 text-[var(--grey-600)]" style={{ fontSize: 13 }}>
              {errorMessage}
            </p>
            <OmniButton
              variant="secondary"
              onClick={() => void loadMeetings(meetingsStore, repository)}
            >
              Retry loading
            </OmniButton>
          </div>
        )}

        {status === "ready" && meetings.length === 0 && (
          <div className="flex max-w-md flex-col items-start gap-[var(--space-3)]">
            <h2
              className="m-0 font-[family-name:var(--font-display)] font-semibold text-[var(--ink)]"
              style={{ fontSize: "var(--text-section-size)", letterSpacing: "var(--text-section-ls)" }}
            >
              No meetings yet
            </h2>
            <p className="m-0 text-[var(--grey-600)]" style={{ fontSize: "var(--text-body-size)", lineHeight: "var(--text-body-lh)" }}>
              Start a capture and the meeting appears here with its two labelled transcript streams
              and your notes. No bot joins your calls — audio is captured on this machine only.
            </p>
            <OmniButton variant="secondary" onClick={onStartCapture}>
              Start capture
            </OmniButton>
          </div>
        )}

        {status === "ready" && meetings.length > 0 && visible.length === 0 && (
          <p className="m-0 text-[var(--grey-600)]" style={{ fontSize: "var(--text-body-size)" }}>
            No meetings match “{query.trim()}”.
          </p>
        )}

        {status === "ready" &&
          groups.map(([dayLabel, rows]) => (
            <section key={dayLabel} aria-label={dayLabel}>
              <div style={{ padding: "40px 0 16px" }}>
                <SectionLabel>{dayLabel}</SectionLabel>
              </div>
              <ul className="m-0 p-0">
                {rows.map((meeting) => (
                  <MeetingRow key={meeting.id} meeting={meeting} onOpen={openDetail} />
                ))}
              </ul>
            </section>
          ))}
        </div>
      </div>

      {selectedId !== null && (
        <LibraryMeetingDetailPane
          meetingId={selectedId}
          loadDetail={detailLoader}
          finalizeMeeting={finalizer}
          onFinalized={() => void loadMeetings(meetingsStore, repository)}
        />
      )}
    </div>
  );
}
