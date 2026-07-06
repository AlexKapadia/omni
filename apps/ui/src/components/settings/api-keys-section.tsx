/**
 * Settings — API keys group card. Masked password inputs; saving hands the
 * value once to the ApiKeyVault interface (mock in-memory now, engine DPAPI
 * later) and clears the field.
 *
 * Security invariant (binding, tested): a saved key value is NEVER echoed
 * back into the DOM — after save only `•••• last-four` metadata renders,
 * matching the onboarding masked-key pattern (`sk-ant-••••R2Qw`).
 */
import { useState } from "react";
import { useStore } from "zustand";
import { OmniButton } from "../button";
import { SettingsGroupCard, SettingsRow } from "./settings-group-card";
import {
  KEY_PROVIDERS,
  KEY_PROVIDER_LABELS,
  saveApiKey,
  type ApiKeyVault,
  type ApiKeysStore,
  type KeyProvider,
} from "../../lib/api-keys-store";

function KeyRow({
  store,
  vault,
  provider,
  last,
}: {
  readonly store: ApiKeysStore;
  readonly vault: ApiKeyVault;
  readonly provider: KeyProvider;
  readonly last: boolean;
}) {
  const rowState = useStore(store, (s) => s.keys[provider]);
  const saving = useStore(store, (s) => s.savingProvider === provider);
  // Draft lives only in this input's local state until save, then is wiped.
  const [draft, setDraft] = useState("");
  const [editing, setEditing] = useState(false);
  const showInput = !rowState.saved || editing;

  const handleSave = async () => {
    const ok = await saveApiKey(store, vault, provider, draft);
    if (ok) {
      setDraft(""); // the plaintext leaves the component the moment it is saved
      setEditing(false);
    }
  };

  return (
    <SettingsRow title={KEY_PROVIDER_LABELS[provider]} last={last}>
      {showInput ? (
        <form
          className="flex items-center gap-[var(--space-2)]"
          onSubmit={(event) => {
            event.preventDefault();
            void handleSave();
          }}
        >
          <input
            type="password"
            autoComplete="off"
            aria-label={`${KEY_PROVIDER_LABELS[provider]} API key`}
            placeholder="Paste key"
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
            className="border border-[var(--grey-300)] bg-transparent font-[family-name:var(--font-mono)] text-[var(--ink)] outline-none placeholder:text-[var(--grey-300)] focus:border-[var(--ink)]"
            style={{
              borderRadius: "var(--radius-control)",
              padding: "6px 10px",
              fontSize: "var(--text-meta-size)",
              width: 200,
            }}
          />
          <OmniButton variant="primary" small type="submit" disabled={saving || draft.length === 0}>
            {saving ? "Saving key" : "Save key"}
          </OmniButton>
          {editing && (
            <OmniButton variant="ghost-dismiss" small onClick={() => setEditing(false)}>
              Cancel
            </OmniButton>
          )}
        </form>
      ) : (
        <div className="flex items-center gap-[var(--space-3)]">
          <span
            className="font-[family-name:var(--font-mono)] text-[var(--grey-600)]"
            style={{ fontSize: "var(--text-transcript-size)" }}
          >
            {/* Metadata only — the value itself never returns to the DOM. */}
            •••••••• {rowState.lastFour}
          </span>
          <span className="font-medium text-[var(--ink)]" style={{ fontSize: "var(--text-meta-size)" }}>
            Saved
          </span>
          <OmniButton variant="ghost" small onClick={() => setEditing(true)}>
            Replace
          </OmniButton>
        </div>
      )}
    </SettingsRow>
  );
}

export function ApiKeysSection({
  store,
  vault,
}: {
  readonly store: ApiKeysStore;
  readonly vault: ApiKeyVault;
}) {
  const errorMessage = useStore(store, (s) => s.errorMessage);
  return (
    <SettingsGroupCard label="API keys">
      {KEY_PROVIDERS.map((provider, index) => (
        <KeyRow
          key={provider}
          store={store}
          vault={vault}
          provider={provider}
          last={index === KEY_PROVIDERS.length - 1 && errorMessage === null}
        />
      ))}
      {errorMessage !== null && (
        <p
          role="alert"
          className="m-0 text-[var(--grey-600)]"
          style={{ padding: "10px 0", fontSize: "var(--text-meta-size)" }}
        >
          {errorMessage}
        </p>
      )}
      <p className="m-0 pb-[var(--space-3)] text-[var(--grey-400)]" style={{ fontSize: 11 }}>
        Keys are encrypted with Windows DPAPI and never leave this device. Mock storage until the
        engine vault lands.
      </p>
    </SettingsGroupCard>
  );
}
