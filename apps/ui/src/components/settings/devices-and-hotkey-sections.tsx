/**
 * Settings — the Devices and Hotkey group cards.
 *
 * Devices are REAL: the engine's devices.list enumeration fills the store with
 * honest pending/unavailable states — never mock names. The push-to-talk
 * hotkey capture records a real key combination and persists it through the
 * REAL settings.update command (optimistic, reverts with an honest message).
 */
import { useState } from "react";
import { useStore } from "zustand";
import { OmniButton } from "../button";
import { SettingsGroupCard, SettingsRow } from "./settings-group-card";
import { setMicrophone, type SettingsStore } from "../../lib/settings-store";
import type { SettingsUpdater } from "../../lib/settings-actions";
import { pushDictationHotkey } from "../../lib/sync-dictation-hotkey";

const SELECT_CLASS =
  "cursor-pointer border-none bg-transparent font-[family-name:var(--font-mono)] text-[var(--grey-600)]";

function DeviceStateNote({ children }: { readonly children: string }) {
  return (
    <span
      className="font-[family-name:var(--font-mono)] text-[var(--ink-secondary)]"
      style={{ fontSize: "var(--text-meta-size)" }}
    >
      {children}
    </span>
  );
}

export function DevicesSection({ store }: { readonly store: SettingsStore }) {
  const devicesSource = useStore(store, (s) => s.devicesSource);
  const microphone = useStore(store, (s) => s.microphone);
  const options = useStore(store, (s) => s.microphoneOptions);
  const systemAudio = useStore(store, (s) => s.systemAudioDevice);
  return (
    <SettingsGroupCard label="Devices">
      <SettingsRow title="Microphone" subCaption="your side of the conversation — labelled Me">
        {devicesSource === "engine" ? (
          <select
            aria-label="Microphone"
            value={microphone}
            onChange={(e) => setMicrophone(store, e.target.value)}
            className={SELECT_CLASS}
            style={{ fontSize: "var(--text-meta-size)" }}
          >
            {options.map((option) => (
              <option key={option} value={option}>
                {option}
              </option>
            ))}
          </select>
        ) : (
          <DeviceStateNote>
            {devicesSource === "pending"
              ? "reading devices from Omni Steroid"
              : "Omni Steroid is offline — devices unavailable"}
          </DeviceStateNote>
        )}
      </SettingsRow>
      <SettingsRow
        title="System audio"
        subCaption="follows the Windows default output — everyone else, labelled Them"
        last
      >
        {devicesSource === "engine" ? (
          <span
            className="font-[family-name:var(--font-mono)] text-[var(--grey-600)]"
            style={{ fontSize: "var(--text-meta-size)" }}
          >
            {systemAudio}
          </span>
        ) : (
          <DeviceStateNote>
            {devicesSource === "pending" ? "reading devices from Omni Steroid" : "unavailable"}
          </DeviceStateNote>
        )}
      </SettingsRow>
    </SettingsGroupCard>
  );
}

function Keycap({ label }: { readonly label: string }) {
  return (
    <kbd
      className="border border-[var(--grey-300)] font-[family-name:var(--font-mono)] text-[var(--ink)]"
      style={{
        borderRadius: "var(--radius-keycap)",
        padding: "3px 8px",
        fontSize: "var(--text-meta-size)",
        boxShadow: "var(--shadow-keycap)",
      }}
    >
      {label}
    </kbd>
  );
}

/** Build the display combo from a real keydown — modifiers first, then key. */
export function comboFromKeyEvent(event: React.KeyboardEvent): readonly string[] | null {
  const key = event.key;
  if (key === "Control" || key === "Shift" || key === "Alt" || key === "Meta") return null;
  const combo: string[] = [];
  if (event.ctrlKey) combo.push("Ctrl");
  if (event.shiftKey) combo.push("Shift");
  if (event.altKey) combo.push("Alt");
  combo.push(key === " " ? "Space" : key.length === 1 ? key.toUpperCase() : key);
  return combo;
}

export function HotkeySection({
  store,
  update,
}: {
  readonly store: SettingsStore;
  readonly update: SettingsUpdater;
}) {
  const keys = useStore(store, (s) => s.settings?.pushToTalkHotkey ?? []);
  const [recording, setRecording] = useState(false);
  const [error, setError] = useState<string | null>(null);
  return (
    <SettingsGroupCard label="Hotkey">
      <SettingsRow
        title="Push to talk"
        subCaption={
          recording ? "press the new combination — Esc cancels" : "hold to dictate anywhere"
        }
        last={error === null}
      >
        <div
          className="flex items-center gap-[var(--space-2)]"
          onKeyDown={(event) => {
            if (!recording) return;
            event.preventDefault();
            if (event.key === "Escape") {
              setRecording(false);
              return;
            }
            const combo = comboFromKeyEvent(event);
            if (combo !== null) {
              setRecording(false);
              void update({ pushToTalkHotkey: combo }).then((r) => {
                setError(r.ok ? null : r.message);
                // On a persisted change, re-register the shell's global hold
                // key live so the new combination works without a restart.
                if (r.ok) void pushDictationHotkey(combo);
              });
            }
          }}
        >
          {keys.map((key) => (
            <Keycap key={key} label={key} />
          ))}
          <OmniButton variant="ghost" small onClick={() => setRecording(!recording)}>
            {recording ? "Cancel" : "Change"}
          </OmniButton>
        </div>
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
