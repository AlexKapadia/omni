/**
 * Compact always-on-top captions: the last few final lines plus in-flight
 * partials. Optimised for glanceability over a shared screen.
 */
import { useStore } from "zustand";
import { type TranscriptPartial, type TranscriptSegment } from "../lib/transcript-store";
import { captionsTranscriptStore } from "./captions-engine-bridge";

const MAX_LINES = 4;

function overlayLines(
  segments: readonly TranscriptSegment[],
  partials: Readonly<Record<"me" | "them", TranscriptPartial | null>>,
): Array<{ key: string; stream: "me" | "them"; label: string; text: string; partial: boolean }> {
  const finals = segments.slice(-MAX_LINES).map((segment) => ({
    key: segment.segmentId,
    stream: segment.stream,
    label: segment.speakerLabel,
    text: segment.text,
    partial: false,
  }));
  const openPartials = (["them", "me"] as const)
    .map((stream) => partials[stream])
    .filter((p): p is TranscriptPartial => p !== null)
    .sort((a, b) => a.tStart - b.tStart)
    .map((partial) => ({
      key: `partial-${partial.stream}-${partial.seq}`,
      stream: partial.stream,
      label: partial.speakerLabel,
      text: partial.text,
      partial: true,
    }));
  const combined = [...finals, ...openPartials];
  return combined.slice(-MAX_LINES);
}

export function CaptionsOverlayView() {
  const segments = useStore(captionsTranscriptStore, (s) => s.segments);
  const partials = useStore(captionsTranscriptStore, (s) => s.partials);
  const captureStatus = useStore(captionsTranscriptStore, (s) => s.captureStatus);
  const lines = overlayLines(segments, partials);

  return (
    <div className="captions-shell" aria-live="polite" aria-label="Live captions overlay">
      <div className="captions-panel">
        {lines.length === 0 ? (
          <p className="captions-idle">
            {captureStatus === "live" ? "Listening…" : "Waiting for capture"}
          </p>
        ) : (
          lines.map((line) => (
            <p
              key={line.key}
              className={
                "captions-line" +
                (line.stream === "them" ? " captions-line--them" : "") +
                (line.partial ? " captions-line--partial" : "")
              }
            >
              {line.label}: {line.text}
              {line.partial ? " …" : ""}
            </p>
          ))
        )}
      </div>
    </div>
  );
}
