/**
 * Settings — Privacy group card, wired to the REAL settings.update command.
 *
 * keep-audio defaults ON (recordings are saved as MP3 on this device
 * alongside the transcript; still local-only — nothing is uploaded); the user
 * can opt out here. The kill switch halts every external call and its
 * sub-caption reflects the engine's live engaged state. Each toggle updates
 * optimistically and reverts with an honest message if the engine refuses.
 */
import { useState } from "react";
import { useStore } from "zustand";
import { SettingsGroupCard, SettingsRow } from "./settings-group-card";
import { ToggleSwitch } from "../toggle-switch";
import type { SettingsStore } from "../../lib/settings-store";
import type { SettingsUpdater } from "../../lib/settings-actions";

export function PrivacySection({
  store,
  update,
  showKillSwitch = true,
}: {
  readonly store: SettingsStore;
  readonly update: SettingsUpdater;
  /** When false, omit kill switch (Recordings tab — lives on System/Pro). */
  readonly showKillSwitch?: boolean;
}) {
  const keepAudio = useStore(store, (s) => s.settings?.keepAudio ?? true);
  const disclosureReminder = useStore(store, (s) => s.settings?.disclosureReminder ?? false);
  const aecEnabled = useStore(store, (s) => s.settings?.aecEnabled ?? false);
  const liveCaptionsOverlay = useStore(store, (s) => s.settings?.liveCaptionsOverlay ?? true);
  const killSwitch = useStore(store, (s) => s.settings?.killSwitch ?? false);
  const killSwitchEngaged = useStore(store, (s) => s.killSwitchEngaged);
  const [error, setError] = useState<string | null>(null);

  const apply = async (partial: Parameters<SettingsUpdater>[0]): Promise<void> => {
    const result = await update(partial);
    setError(result.ok ? null : result.message);
  };

  const lastPrivacyRowIsCaptions = !showKillSwitch;

  return (
    <SettingsGroupCard label="Privacy">
      <SettingsRow
        title="Keep audio after transcription"
        subCaption={
          keepAudio
            ? "recordings are saved as MP3 on this device until you delete them"
            : "off: audio is discarded the moment transcription completes"
        }
      >
        <ToggleSwitch
          checked={keepAudio}
          onChange={(next) => void apply({ keepAudio: next })}
          label="Keep audio after transcription"
        />
      </SettingsRow>
      <SettingsRow
        title="Disclosure reminder"
        subCaption="reminds you to tell participants the meeting is being captured"
      >
        <ToggleSwitch
          checked={disclosureReminder}
          onChange={(next) => void apply({ disclosureReminder: next })}
          label="Disclosure reminder"
        />
      </SettingsRow>
      <SettingsRow
        title="Echo cancellation"
        subCaption="reduces system audio bleeding into your microphone stream"
      >
        <ToggleSwitch
          checked={aecEnabled}
          onChange={(next) => void apply({ aecEnabled: next })}
          label="Echo cancellation"
        />
      </SettingsRow>
      <SettingsRow
        title="Live captions overlay"
        subCaption="shows a floating captions window while capture is live"
        last={lastPrivacyRowIsCaptions && error === null}
      >
        <ToggleSwitch
          checked={liveCaptionsOverlay}
          onChange={(next) => void apply({ liveCaptionsOverlay: next })}
          label="Live captions overlay"
        />
      </SettingsRow>
      {showKillSwitch && (
        <SettingsRow
          title="Pause all cloud AI"
          subCaption={
            killSwitchEngaged
              ? "paused: cloud AI refused — local Ollama still works"
              : "stops every cloud AI request — local Ollama, capture, and notes keep working"
          }
          last={error === null}
        >
          <ToggleSwitch
            checked={killSwitch}
            onChange={(next) => void apply({ killSwitch: next })}
            label="Pause all cloud AI"
          />
        </SettingsRow>
      )}
      {error !== null && (
        <p
          role="alert"
          className="m-0 text-[var(--grey-600)]"
          style={{ padding: "10px 0", fontSize: "var(--text-meta-size)" }}
        >
          {error}
        </p>
      )}
    </SettingsGroupCard>
  );
}
