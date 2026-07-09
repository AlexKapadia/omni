/**
 * Settings — Calendar connect (Essentials): the Google and Outlook connect
 * rows, surfaced as their own group so meeting context is one click away.
 *
 * All wiring is REAL: setup.status seeds the connected flags, connectGoogle /
 * connectMicrosoft start the real OAuth flow, and the completed events flip the
 * state. Connecting is optional; nothing here fabricates a connected state.
 */
import { useEffect, useState } from "react";
import { GoogleConnectPanel } from "../google-connect-panel";
import { MicrosoftConnectPanel } from "../microsoft-connect-panel";
import { SettingsGroupCard, SettingsRow } from "./settings-group-card";
import { connectGoogle, connectMicrosoft, getSetupStatus } from "../../lib/setup-settings-repository";
import { subscribeToGoogleConnect, subscribeToMicrosoftConnect } from "../../lib/setup-settings-transport";

type Credentials = { readonly clientId: string; readonly clientSecret: string };

export function CalendarConnectSection() {
  const [googleConnected, setGoogleConnected] = useState<boolean | null>(null);
  const [googleBusy, setGoogleBusy] = useState(false);
  const [googleMessage, setGoogleMessage] = useState<string | null>(null);
  const [microsoftConnected, setMicrosoftConnected] = useState<boolean | null>(null);
  const [microsoftBusy, setMicrosoftBusy] = useState(false);
  const [microsoftMessage, setMicrosoftMessage] = useState<string | null>(null);

  useEffect(() => {
    void getSetupStatus()
      .then((status) => {
        setGoogleConnected(status.googleConnected);
        setMicrosoftConnected(status.microsoftConnected);
      })
      .catch(() => {
        // Fail closed: an unreachable engine shows "not connected", never a
        // fabricated connected state.
        setGoogleConnected(false);
        setMicrosoftConnected(false);
      });
    const unsubGoogle = subscribeToGoogleConnect((completed) => {
      setGoogleBusy(false);
      setGoogleMessage(completed.message);
      if (completed.ok) setGoogleConnected(true);
    });
    const unsubMicrosoft = subscribeToMicrosoftConnect((completed) => {
      setMicrosoftBusy(false);
      setMicrosoftMessage(completed.message);
      if (completed.ok) setMicrosoftConnected(true);
    });
    return () => {
      unsubGoogle();
      unsubMicrosoft();
    };
  }, []);

  const connectGoogleAccount = async (credentials?: Credentials): Promise<void> => {
    setGoogleBusy(true);
    setGoogleMessage(null);
    try {
      await connectGoogle(undefined, credentials);
    } catch (err) {
      setGoogleBusy(false);
      setGoogleMessage(err instanceof Error ? err.message : "Could not start Google connect.");
    }
  };

  const connectMicrosoftAccount = async (credentials?: Credentials): Promise<void> => {
    setMicrosoftBusy(true);
    setMicrosoftMessage(null);
    try {
      await connectMicrosoft(undefined, credentials);
    } catch (err) {
      setMicrosoftBusy(false);
      setMicrosoftMessage(err instanceof Error ? err.message : "Could not start Microsoft connect.");
    }
  };

  return (
    <SettingsGroupCard label="Calendar">
      <SettingsRow
        title="Google Calendar"
        subCaption="Optional — pre-loads meeting context when connected."
      >
        <span />
      </SettingsRow>
      <div style={{ padding: "0 0 12px" }}>
        <GoogleConnectPanel
          connected={googleConnected === true}
          busy={googleBusy}
          message={googleMessage}
          onConnect={(credentials) => void connectGoogleAccount(credentials)}
          compact
        />
      </div>
      <SettingsRow title="Outlook Calendar" subCaption="Optional — same pre-load for Microsoft 365.">
        <span />
      </SettingsRow>
      <div style={{ padding: "0 0 12px" }}>
        <MicrosoftConnectPanel
          connected={microsoftConnected === true}
          busy={microsoftBusy}
          message={microsoftMessage}
          onConnect={(credentials) => void connectMicrosoftAccount(credentials)}
          compact
        />
      </div>
    </SettingsGroupCard>
  );
}
