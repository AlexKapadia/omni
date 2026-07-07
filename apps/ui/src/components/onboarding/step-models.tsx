/**
 * Onboarding step 4 — download the on-device models and (optionally) connect
 * Google, then finish. Progress bars are driven by REAL models.download events;
 * a failed file surfaces the engine message with a retry. Finish stays disabled
 * until the required keys validate, the vault is set, and models are present.
 */
import { useState } from "react";
import { useStore } from "zustand";
import { OmniButton } from "../button";
import { OnboardingModelProgressRow } from "./onboarding-model-progress-row";
import { modelsPresent, type OnboardingFlowStore } from "../../lib/onboarding-flow-store";

export function StepModels({
  store,
  canFinish,
  finishBlockedReason,
  onDownload,
  onConnectGoogle,
  onFinish,
}: {
  readonly store: OnboardingFlowStore;
  readonly canFinish: boolean;
  readonly finishBlockedReason: string | null;
  readonly onDownload: () => void;
  readonly onConnectGoogle: () => void;
  readonly onFinish: () => void;
}) {
  const started = useStore(store, (s) => s.modelsStarted);
  const files = useStore(store, (s) => s.modelFiles);
  const present = useStore(store, modelsPresent);
  const modelsOk = useStore(store, (s) => s.modelsOk);
  const googleBusy = useStore(store, (s) => s.googleBusy);
  const googleConnected = useStore(store, (s) => s.googleConnected);
  const googleMessage = useStore(store, (s) => s.googleMessage);
  const finishing = useStore(store, (s) => s.finishing);
  const finishError = useStore(store, (s) => s.finishError);
  const [googleSkipped, setGoogleSkipped] = useState(false);

  const hasFailure = modelsOk === false || files.some((f) => f.failedMessage !== null);

  return (
    <div className="flex h-full flex-col">
      <h2
        className="m-0 font-[family-name:var(--font-display)] font-semibold text-[var(--ink)]"
        style={{
          fontSize: "var(--text-title-size)",
          lineHeight: "var(--text-title-lh)",
          letterSpacing: "var(--text-title-ls)",
        }}
      >
        Get the models
      </h2>
      <p
        className="mt-[var(--space-2)] mb-0 text-[var(--grey-600)]"
        style={{ fontSize: "var(--text-body-size)" }}
      >
        Transcription runs on this device. These download once and stay local.
      </p>

      <div className="mt-[var(--space-4)] flex flex-col">
        {present && files.length === 0 ? (
          <p className="m-0 font-medium text-[var(--ink)]" style={{ fontSize: "var(--text-body-size)" }}>
            ✓ models ready
          </p>
        ) : files.length === 0 ? (
          <OmniButton variant="primary" disabled={started} onClick={onDownload}>
            {started ? "Starting download" : "Download"}
          </OmniButton>
        ) : (
          <>
            {files.map((file) => (
              <OnboardingModelProgressRow key={file.file} file={file} />
            ))}
            {present && (
              <p
                className="mt-[var(--space-1)] mb-0 font-medium text-[var(--ink)]"
                style={{ fontSize: "var(--text-meta-size)" }}
              >
                ✓ models ready
              </p>
            )}
            {hasFailure && (
              <OmniButton
                variant="secondary"
                small
                className="mt-[var(--space-2)] self-start"
                onClick={onDownload}
              >
                Retry download
              </OmniButton>
            )}
          </>
        )}
      </div>

      {!googleSkipped && !googleConnected && (
        <div className="mt-[var(--space-6)] flex items-center justify-between gap-[var(--space-3)]">
          <div className="flex min-w-0 flex-col gap-[var(--space-1)]">
            <span className="text-[var(--ink)]" style={{ fontSize: "var(--text-body-size)" }}>
              Connect Google
            </span>
            <span className="text-[var(--grey-400)]" style={{ fontSize: "var(--text-meta-size)" }}>
              optional — calendar and contacts for context. never sends.
            </span>
          </div>
          <div className="flex items-center gap-[var(--space-1)]">
            <OmniButton variant="secondary" small disabled={googleBusy} onClick={onConnectGoogle}>
              {googleBusy ? "Connecting" : "Connect Google"}
            </OmniButton>
            <OmniButton variant="ghost-dismiss" small onClick={() => setGoogleSkipped(true)}>
              Skip
            </OmniButton>
          </div>
        </div>
      )}
      {googleConnected && (
        <p
          className="mt-[var(--space-6)] mb-0 font-medium text-[var(--ink)]"
          style={{ fontSize: "var(--text-meta-size)" }}
        >
          ✓ Google connected
        </p>
      )}
      {!googleConnected && googleMessage !== null && (
        <p role="alert" className="mt-[var(--space-2)] mb-0 text-[var(--grey-600)]" style={{ fontSize: "var(--text-meta-size)" }}>
          {googleMessage}
        </p>
      )}

      <div className="mt-auto flex flex-col items-end gap-[var(--space-2)] pt-[var(--space-6)]">
        {!canFinish && finishBlockedReason !== null && (
          <span className="text-[var(--grey-400)]" style={{ fontSize: "var(--text-meta-size)" }}>
            {finishBlockedReason}
          </span>
        )}
        {finishError !== null && (
          <span role="alert" className="text-[var(--grey-600)]" style={{ fontSize: "var(--text-meta-size)" }}>
            {finishError}
          </span>
        )}
        <OmniButton
          variant="primary"
          disabled={!canFinish || finishing}
          onClick={onFinish}
          style={{ padding: "12px 28px", fontSize: 15 }}
        >
          {finishing ? "Finishing" : "Finish"}
        </OmniButton>
      </div>
    </div>
  );
}
