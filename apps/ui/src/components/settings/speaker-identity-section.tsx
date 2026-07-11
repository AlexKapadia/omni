/**
 * Settings — edit speaker identity and optionally re-enroll voice.
 */
import { useEffect, useState } from "react";
import { useStore } from "zustand";
import { OmniButton } from "../button";
import { SettingsGroupCard, SettingsRow } from "./settings-group-card";
import { recordVoiceSampleWavBase64 } from "../../lib/record-voice-sample";
import { enrollSpeaker } from "../../lib/speaker-enroll-repository";
import { updateSetting, type SettingsUpdater, loadSettings } from "../../lib/settings-actions";
import type { SettingsStore } from "../../lib/settings-store";

export function SpeakerIdentitySection({
  store,
  update = (partial) => updateSetting(store, partial),
}: {
  readonly store: SettingsStore;
  readonly update?: SettingsUpdater;
}) {
  const identity = useStore(store, (s) => s.settings?.speakerIdentity ?? "Me");
  const voiceEnrolled = useStore(store, (s) => s.settings?.speakerVoiceEnrolled ?? false);
  const [name, setName] = useState(identity);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [recordingSeconds, setRecordingSeconds] = useState(0);
  const [focused, setFocused] = useState(false);

  // Sync draft from store when settings reload — skip while the user is typing.
  useEffect(() => {
    if (!focused) setName(identity);
  }, [identity, focused]);

  const save = async (withVoice: boolean): Promise<void> => {
    const trimmed = name.trim();
    if (trimmed.length === 0) {
      setMessage("Enter your display name.");
      return;
    }
    setBusy(true);
    setMessage(null);
    setRecordingSeconds(0);

    let intervalId: any;
    if (withVoice) {
      setRecordingSeconds(4);
      intervalId = setInterval(() => {
        setRecordingSeconds((prev) => Math.max(0, prev - 1));
      }, 1000);
    }

    try {
      const audio = withVoice ? await recordVoiceSampleWavBase64(4) : undefined;
      if (intervalId) clearInterval(intervalId);
      setRecordingSeconds(0);

      await enrollSpeaker(trimmed, audio);
      await update({ speakerIdentity: trimmed });
      // Force settings store reload to sync voiceEnrolled state
      await loadSettings(store);
      
      setMessage(
        withVoice ? "Name and voice sample saved." : "Name saved.",
      );
    } catch (err) {
      if (intervalId) clearInterval(intervalId);
      setRecordingSeconds(0);
      setMessage(err instanceof Error ? err.message : "Could not save speaker profile.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <SettingsGroupCard label="Your voice">
      <SettingsRow
        title="Display Name"
        subCaption="Set your custom name profile to label voice transcripts"
      >
        <div className="flex items-center gap-[var(--space-2)]">
          <input
            aria-label="Speaker display name"
            className="omni-input block w-full max-w-[200px]"
            style={{ height: "var(--control-height-sm)", paddingLeft: 8, paddingRight: 8 }}
            value={name}
            onChange={(e) => setName(e.target.value)}
            onFocus={() => setFocused(true)}
            onBlur={() => setFocused(false)}
          />
          <OmniButton variant="secondary" small disabled={busy} onClick={() => void save(false)}>
            Save name
          </OmniButton>
        </div>
      </SettingsRow>

      <SettingsRow
        title="Host Voice Identity"
        subCaption="Enrolling your voice lets Omni Steroid accurately tag your lines in meeting transcripts."
        last
      >
        <div className="flex flex-col items-end gap-2">
          <div className="flex items-center gap-3">
            <span className={`px-2.5 py-1 rounded-lg text-xs font-semibold flex items-center gap-1.5 ${
              voiceEnrolled 
                ? "bg-[var(--success-bg)] text-[var(--success-text)] border border-[var(--success)]" 
                : "bg-[var(--surface-sunken)] text-[var(--ink-secondary)]"
            }`}>
              <span className={`h-1.5 w-1.5 rounded-full ${voiceEnrolled ? "bg-[var(--success)]" : "bg-[var(--grey-400)]"}`} />
              {voiceEnrolled ? "Voice Enrolled" : "Not Enrolled"}
            </span>
            <OmniButton variant="secondary" small disabled={busy} onClick={() => void save(true)}>
              {busy ? (recordingSeconds > 0 ? `Recording (${recordingSeconds}s)…` : "Saving…") : "Setup Voice"}
            </OmniButton>
          </div>
          {message !== null && (
            <p role="status" className="m-0 text-[var(--grey-600)]" style={{ fontSize: 11 }}>
              {message}
            </p>
          )}
        </div>
      </SettingsRow>
    </SettingsGroupCard>
  );
}
