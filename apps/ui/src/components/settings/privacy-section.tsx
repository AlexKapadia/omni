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
}: {
  readonly store: SettingsStore;
  readonly update: SettingsUpdater;
}) {
  const keepAudio = useStore(store, (s) => s.settings?.keepAudio ?? true);
  const disclosureReminder = useStore(store, (s) => s.settings?.disclosureReminder ?? false);
  const killSwitch = useStore(store, (s) => s.settings?.killSwitch ?? false);
  const killSwitchEngaged = useStore(store, (s) => s.killSwitchEngaged);
  const [error, setError] = useState<string | null>(null);

  const apply = async (partial: Parameters<SettingsUpdater>[0]): Promise<void> => {
    const result = await update(partial);
    setError(result.ok ? null : result.message);
  };

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
        title="Pause all cloud AI"
        subCaption={
          killSwitchEngaged
            ? "paused: every cloud AI request is refused right now"
            : "stops every cloud AI request — capture and notes keep working on this device"
        }
        last={error === null}
      >
        <ToggleSwitch
          checked={killSwitch}
          onChange={(next) => void apply({ killSwitch: next })}
          label="Pause all cloud AI"
        />
      </SettingsRow>
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
