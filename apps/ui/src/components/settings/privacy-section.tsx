/**
 * Settings — Privacy group card: the keep-audio toggle (default OFF — audio
 * is discarded after transcription, the local-only invariant), the
 * disclosure reminder, and the kill switch that halts every external call
 * (fail closed on egress; on-device capture and notes keep working).
 */
import { useStore } from "zustand";
import { SettingsGroupCard, SettingsRow } from "./settings-group-card";
import { ToggleSwitch } from "../toggle-switch";
import {
  setDisclosureReminder,
  setKeepAudio,
  setKillSwitch,
  type SettingsStore,
} from "../../lib/settings-store";

export function PrivacySection({ store }: { readonly store: SettingsStore }) {
  const keepAudio = useStore(store, (s) => s.keepAudio);
  const disclosureReminder = useStore(store, (s) => s.disclosureReminder);
  const killSwitch = useStore(store, (s) => s.killSwitch);
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
          onChange={(next) => setKeepAudio(store, next)}
          label="Keep audio after transcription"
        />
      </SettingsRow>
      <SettingsRow
        title="Disclosure reminder"
        subCaption="reminds you to tell participants the meeting is being captured"
      >
        <ToggleSwitch
          checked={disclosureReminder}
          onChange={(next) => setDisclosureReminder(store, next)}
          label="Disclosure reminder"
        />
      </SettingsRow>
      <SettingsRow
        title="Kill switch"
        subCaption={
          killSwitch
            ? "engaged: every external model call is refused"
            : "halts every external model call — capture and notes keep working on-device"
        }
        last
      >
        <ToggleSwitch
          checked={killSwitch}
          onChange={(next) => setKillSwitch(store, next)}
          label="Kill switch"
        />
      </SettingsRow>
    </SettingsGroupCard>
  );
}
