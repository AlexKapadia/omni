/**
 * Settings — the note-template controls: the active-template selector (built-in
 * options from the REAL settings.get plus the user's custom templates) and a
 * custom-templates editor that adds / renames / removes entries in the
 * custom_templates list. Both persist through the REAL settings.update command.
 *
 * A removed custom template that was active falls back to the first built-in in
 * the same update, so the active template is never left dangling.
 */
import { useState } from "react";
import { useStore } from "zustand";
import { OmniButton } from "../button";
import { SettingsGroupCard, SettingsRow } from "./settings-group-card";
import type { SettingsStore, TemplateOption } from "../../lib/settings-store";
import type { SettingsUpdater } from "../../lib/settings-actions";
import { loadSettings } from "../../lib/settings-actions";
import { updateSettings } from "../../lib/setup-settings-repository";

const INPUT_CLASS =
  "omni-input font-[family-name:var(--font-mono)]";
const INPUT_STYLE = {
  fontSize: "var(--text-meta-size)",
  height: "var(--control-height-sm)",
  width: 180,
  paddingLeft: 10,
  paddingRight: 10,
} as const;

function nameToTemplateId(name: string): string {
  const slug = name
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/^_|_$/g, "");
  return slug.length > 0 ? slug : "custom";
}

function customNameToTemplate(name: string): Record<string, unknown> {
  return {
    template_id: nameToTemplateId(name),
    display_name: name.trim(),
    sections: [{ title: "Summary", guidance: "Capture the main points from this meeting." }],
    tone_rules: "Clear and concise.",
  };
}

function normalizeImportedTemplates(parsed: unknown): Record<string, unknown>[] {
  if (!Array.isArray(parsed)) throw new Error("Expected a JSON array.");
  return parsed.map((entry) => {
    if (typeof entry === "string") {
      const trimmed = entry.trim();
      if (!trimmed) throw new Error("Template name cannot be empty.");
      return customNameToTemplate(trimmed);
    }
    if (typeof entry === "object" && entry !== null) {
      const record = entry as Record<string, unknown>;
      const displayName =
        typeof record.display_name === "string"
          ? record.display_name.trim()
          : typeof record.template_id === "string"
            ? record.template_id.trim()
            : "";
      if (!displayName) throw new Error("Each template needs a display name.");
      if (!Array.isArray(record.sections) || record.sections.length === 0) {
        return customNameToTemplate(displayName);
      }
      return record;
    }
    throw new Error("Each template must be a string or object.");
  });
}

function CustomTemplateRow({
  name,
  siblings,
  onRename,
  onRemove,
}: {
  readonly name: string;
  readonly siblings: readonly string[];
  readonly onRename: (from: string, to: string) => Promise<string | null>;
  readonly onRemove: (name: string) => Promise<string | null>;
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(name);
  const [error, setError] = useState<string | null>(null);

  const save = async (): Promise<void> => {
    const trimmed = draft.trim();
    if (trimmed.length === 0) return setError("Name cannot be empty.");
    if (trimmed !== name && siblings.includes(trimmed)) return setError("That name already exists.");
    const message = await onRename(name, trimmed);
    if (message === null) {
      setEditing(false);
      setError(null);
    } else setError(message);
  };

  return (
    <div className="flex flex-col gap-[var(--space-1)]" style={{ padding: "10px 0" }}>
      <div className="flex items-center justify-between gap-[var(--space-3)]">
        {editing ? (
          <input
            aria-label={`Rename ${name}`}
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            className={INPUT_CLASS}
            style={INPUT_STYLE}
          />
        ) : (
          <span className="text-[var(--ink)]" style={{ fontSize: "var(--text-body-size)" }}>
            {name}
          </span>
        )}
        <div className="flex items-center gap-[var(--space-1)]">
          {editing ? (
            <OmniButton variant="ghost" small onClick={() => void save()}>
              Save
            </OmniButton>
          ) : (
            <OmniButton variant="ghost" small onClick={() => setEditing(true)}>
              Rename
            </OmniButton>
          )}
          <OmniButton
            variant="ghost-dismiss"
            small
            aria-label={`Remove ${name}`}
            onClick={() => void onRemove(name).then((m) => setError(m))}
          >
            Remove
          </OmniButton>
        </div>
      </div>
      {error !== null && (
        <span role="alert" className="text-[var(--grey-600)]" style={{ fontSize: "var(--text-meta-size)" }}>
          {error}
        </span>
      )}
    </div>
  );
}

export function TemplatesSection({
  store,
  update,
}: {
  readonly store: SettingsStore;
  readonly update: SettingsUpdater;
}) {
  const active = useStore(store, (s) => s.settings?.activeTemplate ?? "");
  const custom = useStore(store, (s) => s.settings?.customTemplates ?? []);
  const options = useStore(store, (s) => s.templateOptions);
  const [addDraft, setAddDraft] = useState("");
  const [addError, setAddError] = useState<string | null>(null);

  const firstBuiltin: TemplateOption | undefined = options.find((o) => o.builtin) ?? options[0];

  const persistCustom = async (
    next: readonly string[],
    nextActive?: string,
  ): Promise<string | null> => {
    const partial =
      nextActive === undefined
        ? { customTemplates: next }
        : { customTemplates: next, activeTemplate: nextActive };
    const result = await update(partial);
    return result.ok ? null : result.message;
  };

  const add = async (): Promise<void> => {
    const trimmed = addDraft.trim();
    if (trimmed.length === 0) return setAddError("Name cannot be empty.");
    if (custom.includes(trimmed)) return setAddError("That name already exists.");
    const message = await persistCustom([...custom, trimmed]);
    if (message === null) {
      setAddDraft("");
      setAddError(null);
    } else setAddError(message);
  };

  const rename = (from: string, to: string): Promise<string | null> =>
    persistCustom(
      custom.map((c) => (c === from ? to : c)),
      // activeTemplate is a template_id; map display names through the slugger.
      active === nameToTemplateId(from) ? nameToTemplateId(to) : undefined,
    );

  const remove = (name: string): Promise<string | null> => {
    const next = custom.filter((c) => c !== name);
    // A removed active custom template falls back to the first built-in.
    const nextActive =
      active === nameToTemplateId(name) ? firstBuiltin?.templateId ?? "" : undefined;
    return persistCustom(next, nextActive);
  };

  return (
    <SettingsGroupCard label="Templates">
      <SettingsRow title="Note template" subCaption="shapes how enhanced notes are laid out">
        <select
          aria-label="Note template"
          value={active}
          onChange={(e) => void update({ activeTemplate: e.target.value })}
          className="cursor-pointer border-none bg-transparent font-[family-name:var(--font-mono)] text-[var(--grey-600)]"
          style={{ fontSize: "var(--text-meta-size)" }}
        >
          {options.map((option) => (
            <option key={option.templateId} value={option.templateId}>
              {option.displayName}
            </option>
          ))}
        </select>
      </SettingsRow>
      <div style={{ padding: "14px 0" }} className="flex flex-col">
        <span className="text-[var(--ink-secondary)]" style={{ fontSize: "var(--text-meta-size)" }}>
          {custom.length === 0 ? "no custom templates yet" : "custom templates"}
        </span>
        {custom.map((name) => (
          <CustomTemplateRow
            key={name}
            name={name}
            siblings={custom}
            onRename={rename}
            onRemove={remove}
          />
        ))}
        <form
          className="mt-[var(--space-2)] flex items-center gap-[var(--space-2)]"
          onSubmit={(e) => {
            e.preventDefault();
            void add();
          }}
        >
          <input
            aria-label="New custom template name"
            placeholder="New template name"
            value={addDraft}
            onChange={(e) => setAddDraft(e.target.value)}
            className={INPUT_CLASS}
            style={INPUT_STYLE}
          />
          <OmniButton variant="secondary" small type="submit" disabled={addDraft.trim().length === 0}>
            Add
          </OmniButton>
        </form>
        <div className="mt-[var(--space-2)] flex flex-wrap gap-2">
          <OmniButton
            variant="ghost"
            small
            onClick={() => {
              const blob = new Blob(
                [JSON.stringify(custom.map((name) => customNameToTemplate(name)), null, 2)],
                {
                  type: "application/json",
                },
              );
              const url = URL.createObjectURL(blob);
              const anchor = document.createElement("a");
              anchor.href = url;
              anchor.download = "omni-custom-templates.json";
              anchor.click();
              URL.revokeObjectURL(url);
            }}
          >
            Export JSON
          </OmniButton>
          <OmniButton
            variant="ghost"
            small
            onClick={() => {
              const input = document.createElement("input");
              input.type = "file";
              input.accept = "application/json,.json";
              input.onchange = () => {
                const file = input.files?.[0];
                if (file === undefined) return;
                void file.text().then((text) => {
                  try {
                    const parsed = JSON.parse(text) as unknown;
                    const normalized = normalizeImportedTemplates(parsed);
                    void updateSettings({ custom_templates: normalized }, null).then(() =>
                      void loadSettings(store),
                    );
                  } catch (err) {
                    setAddError(err instanceof Error ? err.message : "Invalid JSON file.");
                  }
                });
              };
              input.click();
            }}
          >
            Import JSON
          </OmniButton>
        </div>
        {addError !== null && (
          <span
            role="alert"
            className="mt-[var(--space-1)] text-[var(--grey-600)]"
            style={{ fontSize: "var(--text-meta-size)" }}
          >
            {addError}
          </span>
        )}
      </div>
    </SettingsGroupCard>
  );
}
