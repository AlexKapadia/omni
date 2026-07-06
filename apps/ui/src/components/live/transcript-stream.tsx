/**
 * Live transcript column (right pane, flex:1, white->grey-50 wash): the two
 * labelled streams as they finalise, plus in-flight partials.
 *
 * Design (components doc §04): mono 12.5px lh 1.6; "Them" = left-aligned
 * grey-400 bubbles (1px grey-400 border, 10px radius); "Me" = right-aligned
 * ink, no bubble; speaker line "Them · 14:07:12" in 10px. Auto-scroll pins to
 * the newest line; scrolling up unpins; the header toggle re-pins.
 */
import { useEffect, useRef, useState } from "react";
import { SectionLabel } from "../section-label";
import {
  formatMeetingClock,
  useTranscript,
  type TranscriptPartial,
  type TranscriptSegment,
} from "../../lib/transcript-store";

/** Pixels from the bottom still counted as "at the bottom". */
const PIN_THRESHOLD_PX = 40;

function SpeakerLine({ stream, tStart }: { readonly stream: "me" | "them"; readonly tStart: number }) {
  return (
    <span
      className="block font-[family-name:var(--font-mono)] text-[var(--grey-400)]"
      style={{ fontSize: 10 }} // doc: in-bubble timestamps are 10px
    >
      {stream === "me" ? "Me" : "Them"} · {formatMeetingClock(tStart)}
    </span>
  );
}

function TranscriptLine({
  stream,
  text,
  tStart,
  inProgress,
}: {
  readonly stream: "me" | "them";
  readonly text: string;
  readonly tStart: number;
  readonly inProgress: boolean;
}) {
  const isMe = stream === "me";
  return (
    <div
      data-stream={stream}
      data-partial={inProgress || undefined}
      className={isMe ? "self-end text-right" : "self-start"}
      style={{ maxWidth: "85%" }}
    >
      <SpeakerLine stream={stream} tStart={tStart} />
      <p
        className={
          "m-0 mt-[var(--space-1)] font-[family-name:var(--font-mono)] " +
          (isMe
            ? "text-[var(--ink)]"
            : "rounded-[var(--radius-bubble)] border border-[var(--grey-400)] text-[var(--grey-400)]")
        }
        style={{
          fontSize: 12.5, // doc-pinned live-transcript size
          lineHeight: "var(--text-transcript-lh)",
          padding: isMe ? 0 : "8px 12px",
          // A partial is honest about being unfinished — ghosted, never solid.
          color: inProgress ? "var(--grey-300)" : undefined,
          borderColor: inProgress && !isMe ? "var(--grey-200)" : undefined,
        }}
      >
        {text}
        {inProgress ? " …" : ""}
      </p>
    </div>
  );
}

export function TranscriptStream() {
  const segments = useTranscript((s) => s.segments);
  const partials = useTranscript((s) => s.partials);
  const [autoScroll, setAutoScroll] = useState(true);
  const scrollRef = useRef<HTMLDivElement | null>(null);

  const openPartials = (["them", "me"] as const)
    .map((stream) => partials[stream])
    .filter((p): p is TranscriptPartial => p !== null)
    .sort((a, b) => a.tStart - b.tStart);

  // Pin to bottom whenever new lines land and the user hasn't scrolled away.
  useEffect(() => {
    const node = scrollRef.current;
    if (node !== null && autoScroll) node.scrollTop = node.scrollHeight;
  }, [segments, partials, autoScroll]);

  const handleScroll = () => {
    const node = scrollRef.current;
    if (node === null) return;
    const atBottom = node.scrollHeight - node.scrollTop - node.clientHeight < PIN_THRESHOLD_PX;
    if (!atBottom && autoScroll) setAutoScroll(false); // scrolling up unpins
  };

  return (
    <aside
      aria-label="Live transcript"
      className="flex min-w-0 flex-col border-l border-[var(--grey-200)]"
      style={{ flex: 1, background: "var(--wash-surface)" }}
    >
      <div
        className="flex items-baseline justify-between"
        style={{ padding: "20px 24px 12px" }} // doc: transcript header padding
      >
        <SectionLabel>Transcript</SectionLabel>
        <button
          type="button"
          aria-pressed={autoScroll}
          onClick={() => {
            const next = !autoScroll;
            setAutoScroll(next);
            const node = scrollRef.current;
            if (next && node !== null) node.scrollTop = node.scrollHeight;
          }}
          className="cursor-pointer border-none bg-transparent font-[family-name:var(--font-mono)] text-[var(--grey-400)] hover:text-[var(--ink)]"
          style={{ fontSize: 11, letterSpacing: "var(--label-ls)" }}
        >
          {autoScroll ? "auto-scroll on" : "auto-scroll off"}
        </button>
      </div>
      <div
        ref={scrollRef}
        onScroll={handleScroll}
        className="flex flex-1 flex-col gap-[var(--space-3)] overflow-y-auto"
        style={{ padding: "8px 24px 24px" }} // doc: stream padding 8px 24px
      >
        {segments.length === 0 && openPartials.length === 0 && (
          <p
            className="m-auto max-w-[24ch] text-center font-[family-name:var(--font-mono)] text-[var(--grey-400)]"
            style={{ fontSize: "var(--text-meta-size)", lineHeight: "var(--text-meta-lh)" }}
          >
            Listening. Words appear here as they are spoken.
          </p>
        )}
        {segments.map((segment: TranscriptSegment) => (
          <TranscriptLine
            key={segment.segmentId}
            stream={segment.stream}
            text={segment.text}
            tStart={segment.tStart}
            inProgress={false}
          />
        ))}
        {openPartials.map((partial) => (
          <TranscriptLine
            key={`partial-${partial.stream}-${partial.seq}`}
            stream={partial.stream}
            text={partial.text}
            tStart={partial.tStart}
            inProgress
          />
        ))}
      </div>
    </aside>
  );
}
