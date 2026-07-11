/**
 * Cartesia voice ID — non-secret identifier mirrored into CARTESIA_VOICE_ID.
 * Local draft + blur persist (same pattern as the Ollama URL field).
 */
import { useEffect, useState } from "react";
import { useStore } from "zustand";

import { SettingsGroupCard, SettingsRow } from "./settings-group-card";
import { updateSetting, type SettingsUpdater } from "../../lib/settings-actions";
import type { SettingsStore } from "../../lib/settings-store";

const INPUT_CLASS =
  "border border-[var(--grey-300)] bg-[var(--canvas)] text-[var(--ink)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--focus-ring)]";
const INPUT_STYLE = {
  height: "var(--control-height-sm)",
  borderRadius: "var(--radius-control)",
  padding: "0 var(--space-2)",
  fontSize: 13,
  minWidth: 220,
} as const;

export function CartesiaVoiceIdSection({
  store,
  update = (partial) => updateSetting(store, partial),
}: {
  readonly store: SettingsStore;
  readonly update?: SettingsUpdater;
}) {
  const saved = useStore(store, (s) => s.settings?.cartesiaVoiceId ?? "");
  const [draft, setDraft] = useState(saved);

  useEffect(() => {
    setDraft(saved);
  }, [saved]);

  const persist = (raw: string): void => {
    const trimmed = raw.trim();
    if (trimmed === saved) return;
    if (trimmed.length > 128) {
      setDraft(saved);
      return;
    }
    void update({ cartesiaVoiceId: trimmed });
  };

  return (
    <SettingsGroupCard label="Naomi voice">
      <SettingsRow
        title="Cartesia voice ID"
        subCaption="Setting wins over CARTESIA_VOICE_ID env when non-empty"
        last
      >
        <input
          aria-label="Cartesia voice ID"
          className={INPUT_CLASS}
          style={INPUT_STYLE}
          value={draft}
          placeholder="voice_…"
          onChange={(e) => setDraft(e.target.value)}
          onBlur={() => persist(draft)}
        />
      </SettingsRow>
    </SettingsGroupCard>
  );
}
