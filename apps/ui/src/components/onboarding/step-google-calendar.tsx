/**
 * Onboarding step 5 — Google Calendar connect with setup instructions.
 * Optional: user may skip and connect later from Settings.
 */
import { useStore } from "zustand";
import { GoogleConnectPanel } from "../google-connect-panel";
import { OmniButton } from "../button";
import type { OnboardingFlowStore } from "../../lib/onboarding-flow-store";

export function StepGoogleCalendar({
  store,
  canFinish,
  finishBlockedReason,
  onConnectGoogle,
  onSkipGoogle,
  onFinish,
}: {
  readonly store: OnboardingFlowStore;
  readonly canFinish: boolean;
  readonly finishBlockedReason: string | null;
  readonly onConnectGoogle: (credentials?: {
    readonly clientId: string;
    readonly clientSecret: string;
  }) => void;
  readonly onSkipGoogle: () => void;
  readonly onFinish: () => void;
}) {
  const googleBusy = useStore(store, (s) => s.googleBusy);
  const googleConnected = useStore(store, (s) => s.googleConnected);
  const googleMessage = useStore(store, (s) => s.googleMessage);
  const googleSkipped = useStore(store, (s) => s.googleSkipped);
  const finishing = useStore(store, (s) => s.finishing);
  const finishError = useStore(store, (s) => s.finishError);

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
        Connect Google Calendar
      </h2>
      <p
        className="mt-[var(--space-2)] mb-0 text-[var(--grey-600)]"
        style={{ fontSize: "var(--text-body-size)" }}
      >
        Optional — pre-loads meeting titles and attendees. Omni never sends email on your behalf.
      </p>

      <div className="mt-[var(--space-4)]">
        {googleSkipped && !googleConnected ? (
          <p className="m-0 text-[var(--ink-secondary)]" style={{ fontSize: 13 }}>
            Skipped — you can connect anytime in Settings → Automation.
          </p>
        ) : (
          <GoogleConnectPanel
            connected={googleConnected}
            busy={googleBusy}
            message={googleMessage}
            onConnect={onConnectGoogle}
            onSkip={googleConnected ? undefined : onSkipGoogle}
          />
        )}
      </div>

      <div className="mt-auto flex flex-col items-end gap-[var(--space-2)] pt-[var(--space-6)]">
        {!canFinish && finishBlockedReason !== null && (
          <span className="text-[var(--ink-secondary)]" style={{ fontSize: "var(--text-meta-size)" }}>
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
