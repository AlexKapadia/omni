/**
 * Settings — the instant-execute whitelist. Each per-intent toggle lets a
 * DICTATION intent of that type run WITHOUT an approval card. Meeting-extracted
 * actions still always need Approve. So this is a security surface: every
 * intent DEFAULTS OFF (deny by default, §5.6), the copy states plainly that a
 * whitelisted dictation intent still gets audited, and email remains draft-only.
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

/** Plain-voice label + the exact effect of enabling each intent (dictation only). */
const INTENT_COPY: Readonly<Record<InstantIntentType, { label: string; effect: string }>> = {
  create_event: {
    label: "Create Google Calendar events",
    effect:
      "dictation: adds events to Google Calendar with no card — still audited; meeting actions still need Approve",
  },
  upsert_contact: {
    label: "Save contacts",
    effect:
      "dictation: writes contacts with no card — still audited; meeting actions still need Approve",
  },
  draft_email: {
    label: "Draft emails",
    effect:
      "dictation: writes Gmail drafts with no card — never sends, still audited; meeting actions still need Approve",
  },
  write_note: {
    label: "Write notes",
    effect:
      "dictation: writes vault notes with no card — still audited; meeting actions still need Approve",
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
    <SettingsGroupCard label="Auto-run dictation commands">
      <p
        className="m-0 text-[var(--ink-secondary)]"
        style={{ fontSize: "var(--text-meta-size)", paddingBottom: 8 }}
      >
        Whitelisted dictation commands skip the approval card. Actions extracted from meetings
        still need Approve.
      </p>
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
