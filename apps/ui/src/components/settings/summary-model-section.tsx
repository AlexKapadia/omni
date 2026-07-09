import { useStore } from "zustand";
import { SettingsGroupCard, SettingsRow } from "./settings-group-card";
import { updateSetting, type SettingsUpdater } from "../../lib/settings-actions";
import type { SettingsStore } from "../../lib/settings-store";

export function SummaryModelSection({
  store,
  update = (partial) => updateSetting(store, partial),
}: {
  readonly store: SettingsStore;
  readonly update?: SettingsUpdater;
}) {
  const summaryModelId = useStore(store, (s) => s.settings?.summaryModelId ?? "gemini-2.5-flash");

  const MODELS = [
    { id: "gemini-2.5-flash", label: "Gemini 2.5 Flash (Fast & Balanced)" },
    { id: "gemini-2.5-pro", label: "Gemini 2.5 Pro (Rich Reasoning)" },
    { id: "claude-sonnet-4-5", label: "Claude 3.5 Sonnet (Premium & Creative)" },
  ];

  return (
    <SettingsGroupCard label="Summary AI model">
      <SettingsRow
        title="Model selection"
        subCaption="Pick the primary LLM used for meeting summaries, action items, and notes."
        last
      >
        <select
          aria-label="Summary AI model"
          className="cursor-pointer border border-[var(--grey-300)] bg-[var(--canvas)] text-[var(--ink)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--focus-ring)]"
          style={{
            height: "var(--control-height-sm)",
            borderRadius: "var(--radius-control)",
            padding: "0 var(--space-2)",
            fontSize: 13,
          }}
          value={summaryModelId}
          onChange={(e) => {
            void update({ summaryModelId: e.target.value });
          }}
        >
          {MODELS.map((m) => (
            <option key={m.id} value={m.id}>
              {m.label}
            </option>
          ))}
        </select>
      </SettingsRow>
    </SettingsGroupCard>
  );
}
