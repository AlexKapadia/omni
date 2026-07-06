/**
 * Capture bar (bottom of the live meeting, 64px): breathing ring, elapsed
 * timer, on-device disclosure copy, the live lag_ms readout (speed is a
 * showcase — instrumented, not asserted), device-recovery notices, and the
 * Stop capture button.
 *
 * Layout per components doc §04: height 64, top hairline, padding 0 32px,
 * gap 24; Stop is a secondary button pushed right.
 */
import { BreathingRing } from "../breathing-ring";
import { OmniButton } from "../button";
import { formatMeetingClock, useTranscript } from "../../lib/transcript-store";
import { requestCaptureStop } from "../../lib/capture-commands";

function MonoMeta({ children, dim = false }: { readonly children: string; readonly dim?: boolean }) {
  return (
    <span
      className={`font-[family-name:var(--font-mono)] ${dim ? "text-[var(--grey-400)]" : "text-[var(--grey-600)]"}`}
      style={{ fontSize: 11 }} // doc: capture-bar meta is mono 11px
    >
      {children}
    </span>
  );
}

export function CaptureBar({ elapsedSeconds }: { readonly elapsedSeconds: number }) {
  const captureStatus = useTranscript((s) => s.captureStatus);
  const lastLagMs = useTranscript((s) => s.lastLagMs);
  const deviceNotice = useTranscript((s) => s.deviceNotice);
  const isLive = captureStatus === "live";
  const isStopping = captureStatus === "stopping";

  return (
    <div
      className="flex shrink-0 items-center border-t border-[var(--grey-200)]"
      style={{ height: 64, padding: "0 32px", gap: "var(--space-6)" }}
    >
      <BreathingRing size={12} breathing={isLive} />
      <span
        className="font-[family-name:var(--font-mono)] text-[var(--ink)]"
        style={{ fontSize: "var(--text-transcript-size)" }} // doc: timer mono 13px
        aria-label="Elapsed capture time"
      >
        {formatMeetingClock(elapsedSeconds)}
      </span>
      <MonoMeta dim>mic + system audio · on-device</MonoMeta>
      <span
        className="font-[family-name:var(--font-mono)] text-[var(--grey-600)]"
        style={{ fontSize: 11 }}
        aria-label="Transcription lag"
      >
        {lastLagMs !== null ? `lag ${Math.round(lastLagMs)} ms` : "lag — ms"}
      </span>
      {deviceNotice !== null && (
        <MonoMeta>
          {`audio moved to ${deviceNotice.deviceName} · recovered in ${Math.round(deviceNotice.recoveredMs)} ms`}
        </MonoMeta>
      )}
      <OmniButton
        variant="secondary"
        className="ml-auto"
        disabled={!isLive}
        onClick={() => requestCaptureStop()}
      >
        {isStopping ? "Stopping capture" : "Stop capture"}
      </OmniButton>
    </div>
  );
}
