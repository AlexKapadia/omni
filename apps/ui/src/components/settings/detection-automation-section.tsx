/**
 * Settings — Automation group: auto-start sources, silence auto-stop, Google Calendar.
 */
import { useEffect, useState } from "react";
import { useStore } from "zustand";
import { GoogleConnectPanel } from "../google-connect-panel";
import { ToggleSwitch } from "../toggle-switch";
import { SettingsGroupCard, SettingsRow } from "./settings-group-card";
import { AUTOSTOP_SILENCE_OPTIONS, DETECTION_SOURCE_OPTIONS } from "../../lib/detection-source-options";
import { getSetupStatus } from "../../lib/setup-settings-repository";
import { connectGoogle } from "../../lib/setup-settings-repository";
import { subscribeToGoogleConnect } from "../../lib/setup-settings-transport";
import type { SettingsStore } from "../../lib/settings-store";
import type { SettingsUpdater } from "../../lib/settings-actions";

export function DetectionAutomationSection({
  store,
  update,
}: {
  readonly store: SettingsStore;
  readonly update: SettingsUpdater;
}) {
  const autoStartSources = useStore(store, (s) => s.settings?.detectionAutoStartSources ?? []);
  const autostopSilenceS = useStore(store, (s) => s.settings?.autostopSilenceS ?? 60);
  const liveCaptionsOverlay = useStore(store, (s) => s.settings?.liveCaptionsOverlay ?? true);
  const [error, setError] = useState<string | null>(null);
  const [googleConnected, setGoogleConnected] = useState<boolean | null>(null);
  const [googleBusy, setGoogleBusy] = useState(false);
  const [googleMessage, setGoogleMessage] = useState<string | null>(null);

  useEffect(() => {
    void getSetupStatus()
      .then((status) => setGoogleConnected(status.googleConnected))
      .catch(() => setGoogleConnected(false));
    const unsub = subscribeToGoogleConnect((completed) => {
      setGoogleBusy(false);
      setGoogleMessage(completed.message);
      if (completed.ok) setGoogleConnected(true);
    });
    return unsub;
  }, []);

  const apply = async (partial: Parameters<SettingsUpdater>[0]): Promise<void> => {
    const result = await update(partial);
    setError(result.ok ? null : result.message);
  };

  const toggleAutoStart = (sourceId: string, enabled: boolean): void => {
    const current = new Set(autoStartSources);
    if (enabled) current.add(sourceId);
    else current.delete(sourceId);
    void apply({ detectionAutoStartSources: [...current].sort() });
  };

  const connectGoogleAccount = async (credentials?: {
    readonly clientId: string;
    readonly clientSecret: string;
  }): Promise<void> => {
    setGoogleBusy(true);
    setGoogleMessage(null);
    try {
      await connectGoogle(undefined, credentials);
    } catch (err) {
      setGoogleBusy(false);
      setGoogleMessage(err instanceof Error ? err.message : "Could not start Google connect.");
    }
  };

  return (
    <SettingsGroupCard label="Automation">
      <SettingsRow
        title="Auto-start capture"
        subCaption="When enabled for a source, Omni starts recording without a toast click once a meeting is detected."
      />
      {DETECTION_SOURCE_OPTIONS.map((option, index) => (
        <SettingsRow
          key={option.id}
          title={option.label}
          last={index === DETECTION_SOURCE_OPTIONS.length - 1}
        >
          <ToggleSwitch
            checked={autoStartSources.includes(option.id)}
            onChange={(next) => toggleAutoStart(option.id, next)}
            label={`Auto-start for ${option.label}`}
          />
        </SettingsRow>
      ))}
      <SettingsRow
        title="Silence auto-stop"
        subCaption="Stop capture after sustained silence on both audio streams."
      >
        <select
          aria-label="Silence auto-stop timeout"
          className="border border-[var(--grey-200)] bg-[var(--paper,#fff)] text-[var(--ink)]"
          style={{ fontSize: 13, padding: "4px 8px", borderRadius: 4 }}
          value={autostopSilenceS}
          onChange={(e) => void apply({ autostopSilenceS: Number(e.target.value) })}
        >
          {AUTOSTOP_SILENCE_OPTIONS.map((opt) => (
            <option key={opt.value} value={opt.value}>
              {opt.label}
            </option>
          ))}
        </select>
      </SettingsRow>
      <SettingsRow
        title="Live captions overlay"
        subCaption="Always-on-top captions bar while capture is running."
      >
        <ToggleSwitch
          checked={liveCaptionsOverlay}
          onChange={(next) => void apply({ liveCaptionsOverlay: next })}
          label="Show live captions overlay"
        />
      </SettingsRow>
      <SettingsRow
        title="Google Calendar"
        subCaption="Optional — pre-loads meeting context when connected."
        last={error === null}
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
      {error !== null && (
        <p role="alert" className="m-0 text-[var(--grey-600)]" style={{ padding: "8px 0", fontSize: 12 }}>
          {error}
        </p>
      )}
    </SettingsGroupCard>
  );
}
