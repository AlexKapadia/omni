/**
 * Shared Microsoft OAuth desktop connect UI — used in onboarding and Settings.
 */
import { useState } from "react";
import { OmniButton } from "./button";

export interface MicrosoftConnectPanelProps {
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

export function MicrosoftConnectPanel({
  connected,
  busy,
  message,
  onConnect,
  onSkip,
  compact = false,
}: MicrosoftConnectPanelProps) {
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
        ✓ Microsoft connected
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
              href="https://portal.azure.com/#view/Microsoft_AAD_RegisteredApps/ApplicationsListBlade"
              target="_blank"
              rel="noreferrer"
              className="text-[var(--ink)] underline"
            >
              Azure App registrations
            </a>
          </p>
          <p className="m-0 mb-2">
            2. Create a <strong>public client</strong> (mobile/desktop) with redirect URI{" "}
            <code>http://127.0.0.1</code>. Add <code>Calendars.Read</code> and offline access.
          </p>
          <p className="m-0">
            3. Paste credentials below, or add <code>MICROSOFT_OAUTH_CLIENT_ID</code> /{" "}
            <code>MICROSOFT_OAUTH_CLIENT_SECRET</code> to <code>.env</code> and restart the engine.
          </p>
        </div>
      )}
      <label
        className="block text-[var(--ink-secondary)]"
        style={{ fontSize: 12 }}
        htmlFor="microsoft-oauth-client-id"
      >
        Client ID
      </label>
      <input
        id="microsoft-oauth-client-id"
        type="text"
        autoComplete="off"
        className="w-full border border-[var(--grey-200)] bg-[var(--paper,#fff)] px-2 py-1 text-[var(--ink)]"
        style={{ fontSize: 13 }}
        value={clientId}
        onChange={(e) => setClientId(e.target.value)}
      />
      <label
        className="block text-[var(--ink-secondary)]"
        style={{ fontSize: 12 }}
        htmlFor="microsoft-oauth-client-secret"
      >
        Client Secret
      </label>
      <input
        id="microsoft-oauth-client-secret"
        type="password"
        autoComplete="off"
        className="w-full border border-[var(--grey-200)] bg-[var(--paper,#fff)] px-2 py-1 text-[var(--ink)]"
        style={{ fontSize: 13 }}
        value={clientSecret}
        onChange={(e) => setClientSecret(e.target.value)}
      />
      <div className="flex items-center gap-[var(--space-2)]">
        <OmniButton variant="secondary" small disabled={busy} onClick={handleConnect}>
          {busy ? "Connecting…" : "Connect Microsoft"}
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
