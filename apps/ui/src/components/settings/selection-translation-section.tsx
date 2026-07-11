/**
 * Selection translation language + a Settings-side "Test translate" so the
 * WS ``selection.translate`` path is reachable without a global hotkey.
 */
import { useState } from "react";
import { useStore } from "zustand";

import { OmniButton } from "../button";
import { SettingsGroupCard, SettingsRow } from "./settings-group-card";
import { translateSelection } from "../../lib/selection-translate-commands";
import { updateSetting, type SettingsUpdater } from "../../lib/settings-actions";
import type { SettingsStore } from "../../lib/settings-store";

const SELECT_CLASS =
  "cursor-pointer border border-[var(--grey-300)] bg-[var(--canvas)] text-[var(--ink)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--focus-ring)]";
const SELECT_STYLE = {
  height: "var(--control-height-sm)",
  borderRadius: "var(--radius-control)",
  padding: "0 var(--space-2)",
  fontSize: 13,
} as const;

const LANG_OPTIONS = [
  "English",
  "Spanish",
  "French",
  "German",
  "Japanese",
  "Chinese",
] as const;

export function SelectionTranslationSection({
  store,
  update = (partial) => updateSetting(store, partial),
}: {
  readonly store: SettingsStore;
  readonly update?: SettingsUpdater;
}) {
  const lang = useStore(store, (s) => s.settings?.selectionTranslationLang ?? "English");
  const [sample, setSample] = useState("Hello, how are you?");
  const [result, setResult] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const runTest = async (): Promise<void> => {
    setBusy(true);
    setError(null);
    setResult(null);
    try {
      setResult(await translateSelection(sample, lang));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Translation failed.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <SettingsGroupCard label="Selection translation">
      <SettingsRow title="Target language" subCaption="Used when target_lang is omitted on selection.translate">
        <select
          aria-label="Selection translation language"
          className={SELECT_CLASS}
          style={SELECT_STYLE}
          value={lang}
          onChange={(e) => void update({ selectionTranslationLang: e.target.value })}
        >
          {LANG_OPTIONS.map((option) => (
            <option key={option} value={option}>
              {option}
            </option>
          ))}
        </select>
      </SettingsRow>
      <SettingsRow title="Test translate" subCaption="Sends sample text through selection.translate" last>
        <div className="flex flex-col gap-2" style={{ minWidth: 220 }}>
          <p className="m-0 text-[var(--grey-600)]" style={{ fontSize: 12 }}>
            Global hotkey coming soon — use Test translate here for now.
          </p>
          <textarea
            aria-label="Sample text to translate"
            className="border border-[var(--grey-300)] bg-[var(--canvas)] text-[var(--ink)]"
            style={{ borderRadius: "var(--radius-control)", fontSize: 13, padding: 8, minHeight: 56 }}
            value={sample}
            onChange={(e) => setSample(e.target.value)}
          />
          <OmniButton
            variant="secondary"
            small
            disabled={busy || !sample.trim()}
            onClick={() => void runTest()}
          >
            {busy ? "Translating…" : "Translate sample"}
          </OmniButton>
          {result !== null && (
            <p className="m-0 text-[var(--ink)]" style={{ fontSize: 13 }} aria-live="polite">
              {result}
            </p>
          )}
          {error !== null && (
            <p role="alert" className="m-0 text-[var(--grey-600)]" style={{ fontSize: 12 }}>
              {error}
            </p>
          )}
        </div>
      </SettingsRow>
    </SettingsGroupCard>
  );
}
