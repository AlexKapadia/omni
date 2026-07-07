/**
 * Onboarding step 3 — API keys. Groq + Gemini are required for a working
 * install; Claude and Cartesia are optional. Keys are masked, saved once
 * through the engine vault (keys.save, DPAPI), and each can be VALIDATED with a
 * real 1-token call (keys.validate). "✓ Valid" appears only after a genuine
 * success; failures show the engine's own message (fail closed).
 */
import { useState } from "react";
import { useStore } from "zustand";
import { OmniButton } from "../button";
import {
  KEY_PROVIDER_LABELS,
  saveApiKey,
  validateApiKey,
  type ApiKeyVault,
  type ApiKeysStore,
  type KeyProvider,
  type KeyValidator,
} from "../../lib/api-keys-store";
import { KEY_PROVIDERS, REQUIRED_KEY_PROVIDERS } from "../../lib/setup-settings-commands";

const INPUT_CLASS =
  "min-w-0 flex-1 border border-[var(--grey-300)] bg-transparent font-[family-name:var(--font-mono)] text-[var(--ink)] outline-none placeholder:text-[var(--grey-300)] focus:border-[var(--ink)]";

function KeyValidationLine({ store, provider }: { readonly store: ApiKeysStore; readonly provider: KeyProvider }) {
  const state = useStore(store, (s) => s.validation[provider]);
  if (state.status === "idle") return null;
  const text =
    state.status === "validating"
      ? "Validating…"
      : state.status === "valid"
        ? `✓ Valid${state.latencyMs !== null ? ` · ${state.latencyMs} ms` : ""}`
        : (state.message ?? "Not valid.");
  return (
    <span
      role={state.status === "valid" ? undefined : "alert"}
      className={state.status === "valid" ? "font-medium text-[var(--ink)]" : "text-[var(--grey-600)]"}
      style={{ fontSize: "var(--text-meta-size)" }}
    >
      {text}
    </span>
  );
}

function KeyEntryRow({
  store,
  vault,
  validator,
  provider,
}: {
  readonly store: ApiKeysStore;
  readonly vault: ApiKeyVault;
  readonly validator: KeyValidator;
  readonly provider: KeyProvider;
}) {
  const saved = useStore(store, (s) => s.keys[provider].saved);
  const lastFour = useStore(store, (s) => s.keys[provider].lastFour);
  const saving = useStore(store, (s) => s.savingProvider === provider);
  const validating = useStore(store, (s) => s.validation[provider].status === "validating");
  const [draft, setDraft] = useState("");
  const required = REQUIRED_KEY_PROVIDERS.includes(provider);

  const save = async () => {
    const ok = await saveApiKey(store, vault, provider, draft);
    if (ok) setDraft("");
  };

  return (
    <div className="flex flex-col gap-[var(--space-2)]" style={{ padding: "10px 0" }}>
      <div className="flex items-center justify-between">
        <span className="text-[var(--ink)]" style={{ fontSize: "var(--text-emphasis-size)" }}>
          {KEY_PROVIDER_LABELS[provider]}
        </span>
        <span
          className="font-[family-name:var(--font-mono)] uppercase text-[var(--ink-secondary)]"
          style={{ fontSize: 11, letterSpacing: "var(--label-ls)" }}
        >
          {required ? "required" : "optional"}
        </span>
      </div>
      {saved ? (
        <div className="flex items-center gap-[var(--space-3)]">
          <span
            className="font-[family-name:var(--font-mono)] text-[var(--grey-600)]"
            style={{ fontSize: "var(--text-transcript-size)" }}
          >
            •••••••• {lastFour}
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
          <KeyValidationLine store={store} provider={provider} />
        </div>
      ) : (
        <form
          className="flex items-center gap-[var(--space-2)]"
          onSubmit={(e) => {
            e.preventDefault();
            void save();
          }}
        >
          <input
            type="password"
            autoComplete="off"
            aria-label={`${KEY_PROVIDER_LABELS[provider]} API key`}
            placeholder="Paste key"
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            className={INPUT_CLASS}
            style={{ borderRadius: "var(--radius-control)", padding: "6px 10px", fontSize: "var(--text-meta-size)" }}
          />
          <OmniButton variant="primary" small type="submit" disabled={saving || draft.length === 0}>
            {saving ? "Saving" : "Save"}
          </OmniButton>
        </form>
      )}
    </div>
  );
}

export function StepKeys({
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
    <div className="flex h-full flex-col">
      <h2
        className="m-0 font-[family-name:var(--font-display)] font-semibold text-[var(--ink)]"
        style={{
          fontSize: "var(--text-title-size)",
          lineHeight: "var(--text-title-lh)",
          letterSpacing: "var(--text-title-ls)",
        }}
      >
        Add your keys
      </h2>
      <p
        className="mt-[var(--space-2)] mb-0 text-[var(--grey-600)]"
        style={{ fontSize: "var(--text-body-size)" }}
      >
        Groq and Gemini power transcription enhancement and answers. Validate each to be sure it
        works.
      </p>
      <div className="mt-[var(--space-4)] flex flex-col">
        {KEY_PROVIDERS.map((provider) => (
          <KeyEntryRow
            key={provider}
            store={store}
            vault={vault}
            validator={validator}
            provider={provider}
          />
        ))}
      </div>
      {errorMessage !== null && (
        <p role="alert" className="m-0 text-[var(--grey-600)]" style={{ fontSize: "var(--text-meta-size)" }}>
          {errorMessage}
        </p>
      )}
      <p className="mt-auto pt-[var(--space-4)] text-[var(--ink-secondary)]" style={{ fontSize: 11 }}>
        Keys are encrypted with Windows DPAPI and never leave this device.
      </p>
    </div>
  );
}
