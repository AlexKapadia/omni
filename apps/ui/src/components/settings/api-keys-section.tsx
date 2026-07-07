/**
 * Settings — API keys group card. Masked password inputs; saving hands the
 * value once to the ApiKeyVault (engine DPAPI) and clears the field. A saved
 * key can be VALIDATED with a real 1-token call — "✓ Valid" appears only after
 * a genuine success; any failure shows the engine's own message honestly.
 *
 * Security invariant (binding, tested): a saved key value is NEVER echoed back
 * into the DOM — after save only `•••• last-four` metadata renders.
 */
import { useState } from "react";
import { useStore } from "zustand";
import { OmniButton } from "../button";
import { SettingsGroupCard, SettingsRow } from "./settings-group-card";
import {
  KEY_PROVIDERS,
  KEY_PROVIDER_LABELS,
  saveApiKey,
  validateApiKey,
  type ApiKeyVault,
  type ApiKeysStore,
  type KeyProvider,
  type KeyValidator,
} from "../../lib/api-keys-store";

function ValidationNote({ store, provider }: { readonly store: ApiKeysStore; readonly provider: KeyProvider }) {
  const state = useStore(store, (s) => s.validation[provider]);
  if (state.status === "idle") return null;
  if (state.status === "validating") {
    return (
      <span className="text-[var(--grey-400)]" style={{ fontSize: "var(--text-meta-size)" }}>
        Validating…
      </span>
    );
  }
  if (state.status === "valid") {
    return (
      <span className="font-medium text-[var(--ink)]" style={{ fontSize: "var(--text-meta-size)" }}>
        ✓ Valid{state.latencyMs !== null ? ` · ${state.latencyMs} ms` : ""}
      </span>
    );
  }
  // invalid | error — surface the engine's own message, never a rosy one.
  return (
    <span role="alert" className="text-[var(--grey-600)]" style={{ fontSize: "var(--text-meta-size)" }}>
      {state.message ?? "Not valid."}
    </span>
  );
}

function KeyRow({
  store,
  vault,
  validator,
  provider,
  last,
}: {
  readonly store: ApiKeysStore;
  readonly vault: ApiKeyVault;
  readonly validator: KeyValidator;
  readonly provider: KeyProvider;
  readonly last: boolean;
}) {
  const rowState = useStore(store, (s) => s.keys[provider]);
  const saving = useStore(store, (s) => s.savingProvider === provider);
  const validating = useStore(store, (s) => s.validation[provider].status === "validating");
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
            style={{ borderRadius: "var(--radius-control)", padding: "6px 10px", fontSize: "var(--text-meta-size)", width: 180 }}
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
        <div className="flex flex-col items-end gap-[var(--space-1)]">
          <div className="flex items-center gap-[var(--space-3)]">
            <span
              className="font-[family-name:var(--font-mono)] text-[var(--grey-600)]"
              style={{ fontSize: "var(--text-transcript-size)" }}
            >
              {/* Metadata only — the value itself never returns to the DOM. */}
              •••••••• {rowState.lastFour}
            </span>
            <OmniButton
              variant="secondary"
              small
              disabled={validating}
              aria-label={`Validate ${KEY_PROVIDER_LABELS[provider]}`}
              onClick={() => void validateApiKey(store, validator, provider)}
            >
              {validating ? "Validating" : "Validate"}
            </OmniButton>
            <OmniButton variant="ghost" small onClick={() => setEditing(true)}>
              Replace
            </OmniButton>
          </div>
          <ValidationNote store={store} provider={provider} />
        </div>
      )}
    </SettingsRow>
  );
}

export function ApiKeysSection({
  store,
  vault,
  validator,
}: {
  readonly store: ApiKeysStore;
  readonly vault: ApiKeyVault;
  readonly validator: KeyValidator;
}) {
  const errorMessage = useStore(store, (s) => s.errorMessage);
  return (
    <SettingsGroupCard label="API keys">
      {KEY_PROVIDERS.map((provider, index) => (
        <KeyRow
          key={provider}
          store={store}
          vault={vault}
          validator={validator}
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
        Keys are encrypted with Windows DPAPI and never leave this device.
      </p>
    </SettingsGroupCard>
  );
}
