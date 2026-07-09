/**
 * Settings — Transcription quality (Essentials). The user picks an accuracy
 * tier (Fast / Enhanced / Cloud) in plain language; the underlying model names
 * (Parakeet, Whisper, etc.) are an implementation detail hidden behind an
 * "Advanced model options" disclosure that only matters to power users. Every
 * change persists through the REAL settings.update command.
 */
import { useStore } from "zustand";

import { SettingsGroupCard, SettingsRow } from "./settings-group-card";

import { updateSetting, type SettingsUpdater } from "../../lib/settings-actions";

import type { SettingsStore } from "../../lib/settings-store";

type SttTier = "fast" | "enhanced" | "cloud";

// Human tier labels — deliberately free of model names (hidden by default per
// the rehaul glossary: "Fast (on-device) / Enhanced / Cloud").
const TIER_LABELS: Record<SttTier, string> = {
  fast: "Fast — on device",
  enhanced: "Enhanced — on device",
  cloud: "Cloud — bring your own key",
};

const TIER_SETTINGS: Record<SttTier, { sttEngine: string; sttModelId: string }> = {
  fast: { sttEngine: "parakeet", sttModelId: "" },
  enhanced: { sttEngine: "whisper", sttModelId: "large-v3" },
  cloud: { sttEngine: "openai_compatible", sttModelId: "whisper-1" },
};

function tierFromSettings(engine: string): SttTier {
  if (engine === "openai_compatible") return "cloud";
  if (engine === "whisper") return "enhanced";
  return "fast";
}

export function TranscriptionBackendSection({
  store,
  update = (partial) => updateSetting(store, partial),
}: {
  readonly store: SettingsStore;
  readonly update?: SettingsUpdater;
}) {
  const engine = useStore(store, (s) => s.settings?.sttEngine ?? "parakeet");
  const modelId = useStore(store, (s) => s.settings?.sttModelId ?? "");
  const baseUrl = useStore(store, (s) => s.settings?.sttOpenaiBaseUrl ?? "");
  const tier = tierFromSettings(engine);

  return (
    <SettingsGroupCard label="Transcription quality">
      <SettingsRow
        title="Accuracy"
        subCaption="Live meetings transcribe on device; imports and re-transcribes use this quality."
        last={tier === "fast"}
      >
        <select
          aria-label="Transcription accuracy"
          className="cursor-pointer border border-[var(--grey-300)] bg-[var(--canvas)] text-[var(--ink)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--focus-ring)]"
          style={{ height: "var(--control-height-sm)", borderRadius: "var(--radius-control)", padding: "0 var(--space-2)", fontSize: 13 }}
          value={tier}
          onChange={(e) => {
            const next = TIER_SETTINGS[e.target.value as SttTier];
            void update({
              sttEngine: next.sttEngine as "parakeet" | "whisper" | "openai_compatible",
              sttModelId: next.sttModelId,
            });
          }}
        >
          {(Object.keys(TIER_LABELS) as SttTier[]).map((key) => (
            <option key={key} value={key}>
              {TIER_LABELS[key]}
            </option>
          ))}
        </select>
      </SettingsRow>

      {tier !== "fast" && (
        <details style={{ padding: "12px 0 4px" }}>
          <summary
            className="cursor-pointer text-[var(--ink-secondary)]"
            style={{ fontSize: "var(--text-meta-size)" }}
          >
            Advanced model options
          </summary>
          <div className="mt-[var(--space-2)] flex flex-col gap-[var(--space-2)]">
            {tier === "enhanced" && (
              <SettingsRow title="Model" last>
                <input
                  aria-label="Enhanced model id"
                  className="omni-input w-full"
                  style={{ height: "var(--control-height-sm)", paddingLeft: 8, paddingRight: 8 }}
                  value={modelId}
                  placeholder="large-v3"
                  onChange={(e) => void update({ sttModelId: e.target.value })}
                />
              </SettingsRow>
            )}
            {tier === "cloud" && (
              <>
                <SettingsRow title="Cloud model id">
                  <input
                    aria-label="Cloud model id"
                    className="omni-input w-full"
                    style={{ height: "var(--control-height-sm)", paddingLeft: 8, paddingRight: 8 }}
                    value={modelId}
                    placeholder="whisper-1"
                    onChange={(e) => void update({ sttModelId: e.target.value })}
                  />
                </SettingsRow>
                <SettingsRow title="Cloud endpoint" last>
                  <input
                    aria-label="Cloud endpoint"
                    className="omni-input w-full"
                    style={{ height: "var(--control-height-sm)", paddingLeft: 8, paddingRight: 8 }}
                    value={baseUrl}
                    placeholder="https://api.openai.com/v1"
                    onChange={(e) => void update({ sttOpenaiBaseUrl: e.target.value })}
                  />
                </SettingsRow>
              </>
            )}
          </div>
        </details>
      )}
    </SettingsGroupCard>
  );
}
