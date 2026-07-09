/**
 * Settings — the instant-execute whitelist. Each per-intent toggle lets a
 * dictation intent of that type run WITHOUT an approval card. So this is a
 * security surface: every intent DEFAULTS OFF (deny by default, §5.6), the
 * copy states plainly that a whitelisted intent still gets audited, and email
 * remains draft-only regardless.
 *
 * Persisted via instant_execute_whitelist (the array of enabled intent types).
 */
import { useState } from "react";
import { useStore } from "zustand";
import { SettingsGroupCard, SettingsRow } from "./settings-group-card";
import { ToggleSwitch } from "../toggle-switch";
import { INSTANT_INTENT_TYPES, type InstantIntentType } from "../../lib/setup-settings-commands";
import type { SettingsStore } from "../../lib/settings-store";
import type { SettingsUpdater } from "../../lib/settings-actions";

/** Plain-voice label + the exact effect of enabling each intent. */
const INTENT_COPY: Readonly<Record<InstantIntentType, { label: string; effect: string }>> = {
  create_event: {
    label: "Create calendar events",
    effect: "adds events straight to your calendar, no card — still audited",
  },
  upsert_contact: {
    label: "Save contacts",
    effect: "writes contacts straight through, no card — still audited",
  },
  draft_email: {
    label: "Draft emails",
    effect: "writes Gmail drafts straight through, no card — never sends, still audited",
  },
  write_note: {
    label: "Write notes",
    effect: "writes vault notes straight through, no card — still audited",
  },
};

export function InstantExecuteWhitelistSection({
  store,
  update,
}: {
  readonly store: SettingsStore;
  readonly update: SettingsUpdater;
}) {
  const whitelist = useStore(store, (s) => s.settings?.instantExecuteWhitelist ?? []);
  const [error, setError] = useState<string | null>(null);

  const toggle = async (intent: InstantIntentType, next: boolean): Promise<void> => {
    const enabled = new Set(whitelist);
    if (next) enabled.add(intent);
    else enabled.delete(intent);
    // Preserve the canonical order so the persisted array is deterministic.
    const nextList = INSTANT_INTENT_TYPES.filter((i) => enabled.has(i));
    const result = await update({ instantExecuteWhitelist: nextList });
    setError(result.ok ? null : result.message);
  };

  return (
    <SettingsGroupCard label="Auto-run safe actions">
      {INSTANT_INTENT_TYPES.map((intent, index) => {
        const enabled = whitelist.includes(intent);
        const copy = INTENT_COPY[intent];
        return (
          <SettingsRow
            key={intent}
            title={copy.label}
            subCaption={enabled ? copy.effect : "off: needs an approval card each time"}
            last={index === INSTANT_INTENT_TYPES.length - 1 && error === null}
          >
            <ToggleSwitch
              checked={enabled}
              onChange={(next) => void toggle(intent, next)}
              label={`Auto-run ${copy.label}`}
            />
          </SettingsRow>
        );
      })}
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
