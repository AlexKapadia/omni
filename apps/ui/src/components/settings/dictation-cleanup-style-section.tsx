import { useStore } from "zustand";
import { SettingsGroupCard, SettingsRow } from "./settings-group-card";
import { updateSetting, type SettingsUpdater } from "../../lib/settings-actions";
import type { SettingsStore } from "../../lib/settings-store";

export function DictationCleanupStyleSection({
  store,
  update = (partial) => updateSetting(store, partial),
}: {
  readonly store: SettingsStore;
  readonly update?: SettingsUpdater;
}) {
  const style = useStore(store, (s) => s.settings?.dictationCleanupStyle ?? "classic");

  return (
    <SettingsGroupCard label="Dictation cleanup">
      <SettingsRow title="Style preset" last>
        <select
          aria-label="Dictation cleanup style"
          className="cursor-pointer border border-[var(--grey-300)] bg-[var(--canvas)] text-[var(--ink)] px-2 py-1 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--focus-ring)]"
          style={{ borderRadius: "var(--radius-control)", fontSize: "var(--text-transcript-size)" }}
          value={style}
          onChange={(e) =>
            void update({
              dictationCleanupStyle: e.target.value as "classic" | "business" | "tech",
            })
          }
        >
          <option value="classic">Classic</option>
          <option value="business">Business</option>
          <option value="tech">Technical</option>
        </select>
      </SettingsRow>
    </SettingsGroupCard>
  );
}
