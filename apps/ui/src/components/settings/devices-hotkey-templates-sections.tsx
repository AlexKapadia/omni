/**
 * Settings — the Devices, Hotkey and Templates group cards. Grouped in one
 * file because each is a thin, single-card binding of settings-store state
 * to the shared row primitives; the store logic they drive lives (and is
 * tested) in settings-store.ts.
 *
 * Devices are REAL: the engine's devices.list enumeration fills the store
 * (engine-devices.ts) with honest pending/unavailable states — never mock
 * names. Hotkey capture is real (records an actual key combination).
 */
import { useState } from "react";
import { useStore } from "zustand";
import { OmniButton } from "../button";
import { SettingsGroupCard, SettingsRow } from "./settings-group-card";
import {
  setActiveTemplate,
  setMicrophone,
  setPushToTalkKeys,
  type SettingsStore,
} from "../../lib/settings-store";

const SELECT_CLASS =
  "cursor-pointer border-none bg-transparent font-[family-name:var(--font-mono)] text-[var(--grey-600)]";

function DeviceStateNote({ children }: { readonly children: string }) {
  return (
    <span
      className="font-[family-name:var(--font-mono)] text-[var(--grey-400)]"
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
              ? "reading devices from the engine"
              : "engine offline — devices unavailable"}
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
            {devicesSource === "pending" ? "reading devices from the engine" : "unavailable"}
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
function comboFromKeyEvent(event: React.KeyboardEvent): readonly string[] | null {
  const key = event.key;
  if (key === "Control" || key === "Shift" || key === "Alt" || key === "Meta") return null;
  const combo: string[] = [];
  if (event.ctrlKey) combo.push("Ctrl");
  if (event.shiftKey) combo.push("Shift");
  if (event.altKey) combo.push("Alt");
  combo.push(key === " " ? "Space" : key.length === 1 ? key.toUpperCase() : key);
  return combo;
}

export function HotkeySection({ store }: { readonly store: SettingsStore }) {
  const keys = useStore(store, (s) => s.pushToTalkKeys);
  const [recording, setRecording] = useState(false);
  return (
    <SettingsGroupCard label="Hotkey">
      <SettingsRow
        title="Push to talk"
        subCaption={recording ? "press the new combination — Esc cancels" : "hold to dictate anywhere"}
        last
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
              setPushToTalkKeys(store, combo);
              setRecording(false);
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
    </SettingsGroupCard>
  );
}

export function TemplatesSection({ store }: { readonly store: SettingsStore }) {
  const active = useStore(store, (s) => s.activeTemplate);
  const options = useStore(store, (s) => s.templateOptions);
  return (
    <SettingsGroupCard label="Templates">
      <SettingsRow title="Note template" subCaption="shapes how enhanced notes are laid out" last>
        <select
          aria-label="Note template"
          value={active}
          onChange={(e) => setActiveTemplate(store, e.target.value)}
          className={SELECT_CLASS}
          style={{ fontSize: "var(--text-meta-size)" }}
        >
          {options.map((option) => (
            <option key={option} value={option}>
              {option}
            </option>
          ))}
        </select>
      </SettingsRow>
    </SettingsGroupCard>
  );
}
