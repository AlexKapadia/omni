/**
 * Live meeting — the flagship screen: notepad left (flex:2), live transcript
 * right (flex:1), capture bar below, answers panel floating bottom-right.
 *
 * Transcript, lag and capture lifecycle are LIVE-WIRED to the engine's
 * transcript.partial / transcript.final / capture.* events via
 * transcript-store; answers-panel hits come from live-answers-store, fed by
 * the engine's answers.hit events (M3 live tier). States: idle (pre-capture,
 * honest about an offline engine), starting, live, stopped, and error — no
 * state is faked.
 */
import { useEffect, useState, type ReactNode } from "react";
import { OmniButton } from "../components/button";
import { AnswersPanel } from "../components/live/answers-panel";
import { LiveSummaryPanel } from "../components/live/live-summary-panel";
import { LiveTranslationPanel } from "../components/live/live-translation-panel";
import { VaultSuggestionsPanel } from "../components/live/vault-suggestions-panel";
import { CaptureBar } from "../components/live/capture-bar";
import { FinalizeMeetingPanel } from "../components/live/finalize-meeting-panel";
import { MeetingDetectedToast } from "../components/live/meeting-detected-toast";
import { NotepadPane } from "../components/live/notepad-pane";
import { TranscriptStream } from "../components/live/transcript-stream";
import { requestCaptureStart } from "../lib/capture-commands";
import { useEngineStatus } from "../lib/engine-status-store";
import { bindNotepadToMeeting, notepadStore } from "../lib/notepad-store";
import { useTranscript } from "../lib/transcript-store";

/** Ticks once a second while live so the timer and bubbles share one clock. */
function useElapsedSeconds(startedAtMs: number | null): number {
  const [nowMs, setNowMs] = useState(() => Date.now());
  useEffect(() => {
    if (startedAtMs === null) return undefined;
    const timer = setInterval(() => setNowMs(Date.now()), 1000);
    return () => clearInterval(timer);
  }, [startedAtMs]);
  if (startedAtMs === null) return 0;
  return Math.max(0, (nowMs - startedAtMs) / 1000);
}

function PreCaptureState({
  heading,
  body,
  errorMessage,
  children,
}: {
  readonly heading: string;
  readonly body: string;
  readonly errorMessage: string | null;
  /** Extra flow content (e.g. the finalize panel after a stop). */
  readonly children?: ReactNode;
}) {
  const engineStatus = useEngineStatus((s) => s.status);
  const captureStatus = useTranscript((s) => s.captureStatus);
  const engineDown = engineStatus !== "connected";
  const starting = captureStatus === "starting";

  return (
    <div className="flex h-full items-center justify-center">
      <div className="flex max-w-md flex-col items-start gap-[var(--space-3)] px-[var(--space-8)]">
        <h1
          className="m-0 font-[family-name:var(--font-display)] font-semibold text-[var(--ink)]"
          style={{
            fontSize: "var(--text-title-size)",
            lineHeight: "var(--text-title-lh)",
            letterSpacing: "var(--text-title-ls)",
          }}
        >
          {heading}
        </h1>
        <p
          className="m-0 text-[var(--grey-600)]"
          style={{ fontSize: "var(--text-body-size)", lineHeight: "var(--text-body-lh)" }}
        >
          {body}
        </p>
        <OmniButton
          variant="primary"
          disabled={engineDown || starting}
          onClick={() => requestCaptureStart()}
        >
          {starting ? "Starting capture" : "Start capture"}
        </OmniButton>
        {engineDown && (
          <p className="m-0 text-[var(--ink-secondary)]" style={{ fontSize: 13 }}>
            The engine is offline — capture needs the engine running on this device.
          </p>
        )}
        {errorMessage !== null && (
          <p role="alert" className="m-0 text-[var(--grey-600)]" style={{ fontSize: 13 }}>
            {errorMessage}
          </p>
        )}
        {children}
      </div>
    </div>
  );
}

export function LiveMeetingScreen() {
  const captureStatus = useTranscript((s) => s.captureStatus);
  const meetingId = useTranscript((s) => s.meetingId);
  const startedAtMs = useTranscript((s) => s.captureStartedAtMs);
  const errorMessage = useTranscript((s) => s.errorMessage);
  const elapsedSeconds = useElapsedSeconds(startedAtMs);

  // A new meeting gets a fresh notepad page; the same meeting keeps its buffer.
  useEffect(() => {
    if (meetingId !== null) bindNotepadToMeeting(notepadStore, meetingId);
  }, [meetingId]);

  if (captureStatus === "idle" || captureStatus === "starting") {
    return (
      <div className="relative h-full">
        <MeetingDetectedToast />
        <PreCaptureState
          heading="Live meeting"
          body="Capture the room and your mic as two labelled streams, transcribed on this device. No bot joins the call and nothing leaves this machine."
          errorMessage={errorMessage}
        />
      </div>
    );
  }

  if (captureStatus === "stopped" || captureStatus === "error") {
    return (
      <div className="relative h-full">
        <MeetingDetectedToast />
        <PreCaptureState
          heading={captureStatus === "error" ? "Capture ended with an error" : "Capture stopped"}
          body={
            captureStatus === "error"
              ? "The engine reported an error and capture ended. Everything transcribed so far is saved on this device."
              : "The meeting is saved on this device. Finalize it to fuse your notes with the transcript into the enhanced vault note."
          }
          errorMessage={errorMessage}
        >
          {/* Finalize needs a real ended meeting; the buffer travels verbatim. */}
          {meetingId !== null && <FinalizeMeetingPanel meetingId={meetingId} />}
        </PreCaptureState>
      </div>
    );
  }

  // live / stopping: the full flagship layout.
  return (
    <div className="relative flex h-full min-h-0 flex-col">
      <MeetingDetectedToast />
      <div className="flex min-h-0 flex-1 flex-col">
        <div className="flex min-h-0 flex-1">
          <div className="flex min-w-0 flex-col" style={{ flex: 2 }}>
            <LiveSummaryPanel />
            <LiveTranslationPanel />
            <NotepadPane meetingTitle="Live meeting" elapsedSeconds={elapsedSeconds} />
          </div>
          <TranscriptStream />
        </div>
      </div>
      <CaptureBar elapsedSeconds={elapsedSeconds} />
      <VaultSuggestionsPanel />
      <AnswersPanel />
    </div>
  );
}
