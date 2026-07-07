/**
 * Settings — Privacy group card, wired to the REAL settings.update command.
 *
 * keep-audio defaults OFF (audio discarded after transcription — the
 * local-only invariant); the kill switch halts every external call and its
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
  const keepAudio = useStore(store, (s) => s.settings?.keepAudio ?? false);
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
            ? "recordings stay on this device until you delete them"
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
        title="Kill switch"
        subCaption={
          killSwitchEngaged
            ? "engaged: every external model call is refused"
            : "halts every external model call — capture and notes keep working on-device"
        }
        last={error === null}
      >
        <ToggleSwitch
          checked={killSwitch}
          onChange={(next) => void apply({ killSwitch: next })}
          label="Kill switch"
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
