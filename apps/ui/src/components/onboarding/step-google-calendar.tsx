import { useStore } from "zustand";
import { GoogleConnectPanel } from "../google-connect-panel";
import type { OnboardingFlowStore } from "../../lib/onboarding-flow-store";

export function StepGoogleCalendar({
  store,
  onConnectGoogle,
}: {
  readonly store: OnboardingFlowStore;
  readonly onConnectGoogle: (credentials?: {
    readonly clientId: string;
    readonly clientSecret: string;
  }) => void;
}) {
  const googleBusy = useStore(store, (s) => s.googleBusy);
  const googleConnected = useStore(store, (s) => s.googleConnected);
  const googleMessage = useStore(store, (s) => s.googleMessage);

  return (
    <div className="flex flex-col gap-[var(--space-2)]">
      <p
        className="m-0 text-[var(--ink-secondary)]"
        style={{ fontSize: "var(--text-body-size)" }}
      >
        Optional — pre-loads meeting titles and attendees. Omni Steroid never sends email on your behalf.
      </p>

      <div className="mt-[var(--space-2)]">
        <GoogleConnectPanel
          connected={googleConnected}
          busy={googleBusy}
          message={googleMessage}
          onConnect={onConnectGoogle}
          compact
        />
      </div>

      <div className="mt-[var(--space-2)] flex items-center gap-[var(--space-2)]">
        <span className="text-[var(--ink-secondary)]" style={{ fontSize: "var(--text-meta-size)" }}>
          Status:
        </span>
        {googleConnected ? (
          <span className="font-semibold text-[var(--success-text)] flex items-center gap-1" style={{ fontSize: "var(--text-meta-size)" }}>
            <svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round">
              <polyline points="20 6 9 17 4 12" />
            </svg>
            Connected
          </span>
        ) : (
          <span className="text-[var(--ink-secondary)]" style={{ fontSize: "var(--text-meta-size)" }}>
            Not connected
          </span>
        )}
      </div>
    </div>
  );
}
