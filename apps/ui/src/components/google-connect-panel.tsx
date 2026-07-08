/**
 * Shared Google OAuth desktop connect UI — used in onboarding and Settings.
 * Credentials may be pasted here or supplied via .env (GOOGLE_OAUTH_CLIENT_*).
 */
import { useState } from "react";
import { OmniButton } from "./button";

export interface GoogleConnectPanelProps {
  readonly connected: boolean;
  readonly busy: boolean;
  readonly message: string | null;
  readonly onConnect: (credentials?: {
    readonly clientId: string;
    readonly clientSecret: string;
  }) => void;
  readonly onSkip?: () => void;
  readonly compact?: boolean;
}

export function GoogleConnectPanel({
  connected,
  busy,
  message,
  onConnect,
  onSkip,
  compact = false,
}: GoogleConnectPanelProps) {
  const [clientId, setClientId] = useState("");
  const [clientSecret, setClientSecret] = useState("");

  const handleConnect = (): void => {
    const trimmedId = clientId.trim();
    const trimmedSecret = clientSecret.trim();
    if ((trimmedId.length > 0) !== (trimmedSecret.length > 0)) {
      return;
    }
    onConnect(
      trimmedId.length > 0 ? { clientId: trimmedId, clientSecret: trimmedSecret } : undefined,
    );
  };

  if (connected) {
    return (
      <p className="m-0 font-medium text-[var(--ink)]" style={{ fontSize: compact ? 13 : 14 }}>
        ✓ Google connected
      </p>
    );
  }

  return (
    <div className="flex flex-col gap-[var(--space-3)]">
      {!compact && (
        <div className="text-[var(--grey-600)]" style={{ fontSize: 12 }}>
          <p className="m-0 mb-2">
            1. Open{" "}
            <a
              href="https://console.cloud.google.com/apis/credentials"
              target="_blank"
              rel="noreferrer"
              className="text-[var(--ink)] underline"
            >
              Google Cloud Console → Credentials
            </a>
          </p>
          <p className="m-0 mb-2">
            2. Create an <strong>OAuth client ID</strong> (Desktop app). Enable Calendar, People,
            and Gmail APIs.
          </p>
          <p className="m-0">
            3. Paste credentials below, or add <code>GOOGLE_OAUTH_CLIENT_ID</code> /{" "}
            <code>GOOGLE_OAUTH_CLIENT_SECRET</code> to <code>.env</code> and restart the engine.
          </p>
        </div>
      )}
      <label className="block text-[var(--ink-secondary)]" style={{ fontSize: 12 }} htmlFor="google-oauth-client-id">
        Client ID
      </label>
      <input
        id="google-oauth-client-id"
        type="text"
        autoComplete="off"
        className="w-full border border-[var(--grey-200)] bg-[var(--paper,#fff)] px-2 py-1 text-[var(--ink)]"
        style={{ fontSize: 13 }}
        value={clientId}
        onChange={(e) => setClientId(e.target.value)}
      />
      <label className="block text-[var(--ink-secondary)]" style={{ fontSize: 12 }} htmlFor="google-oauth-client-secret">
        Client Secret
      </label>
      <input
        id="google-oauth-client-secret"
        type="password"
        autoComplete="off"
        className="w-full border border-[var(--grey-200)] bg-[var(--paper,#fff)] px-2 py-1 text-[var(--ink)]"
        style={{ fontSize: 13 }}
        value={clientSecret}
        onChange={(e) => setClientSecret(e.target.value)}
      />
      <div className="flex items-center gap-[var(--space-2)]">
        <OmniButton variant="secondary" small disabled={busy} onClick={handleConnect}>
          {busy ? "Connecting…" : "Connect Google"}
        </OmniButton>
        {onSkip !== undefined && (
          <OmniButton variant="ghost-dismiss" small onClick={onSkip}>
            Skip for now
          </OmniButton>
        )}
      </div>
      {message !== null && (
        <p role="status" className="m-0 text-[var(--grey-600)]" style={{ fontSize: 12 }}>
          {message}
        </p>
      )}
    </div>
  );
}
