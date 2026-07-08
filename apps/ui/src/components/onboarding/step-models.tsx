/**
 * Onboarding step 4 — download the on-device models, then continue to
 * Google Calendar setup. Progress bars are driven by REAL models.download events.
 */
import { useStore } from "zustand";
import { OmniButton } from "../button";
import { OnboardingModelProgressRow } from "./onboarding-model-progress-row";
import { modelsPresent, type OnboardingFlowStore } from "../../lib/onboarding-flow-store";

export function StepModels({
  store,
  onDownload,
}: {
  readonly store: OnboardingFlowStore;
  readonly onDownload: () => void;
}) {
  const started = useStore(store, (s) => s.modelsStarted);
  const files = useStore(store, (s) => s.modelFiles);
  const present = useStore(store, modelsPresent);
  const modelsOk = useStore(store, (s) => s.modelsOk);

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
    </div>
  );
}
