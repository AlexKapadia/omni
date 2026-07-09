import { useState, type ReactNode } from "react";
import { useStore } from "zustand";
import { motion, AnimatePresence } from "framer-motion";
import { OmniButton } from "../button";
import { StepGoogleCalendar } from "./step-google-calendar";
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
import type { OnboardingFlowStore } from "../../lib/onboarding-flow-store";

function EyeIcon() {
  return (
    <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="opacity-75">
      <path d="M2.062 12.348a1 1 0 0 1 0-.696 10.75 10.75 0 0 1 19.876 0 1 1 0 0 1 0 .696 10.75 10.75 0 0 1-19.876 0z" />
      <circle cx="12" cy="12" r="3" />
    </svg>
  );
}

function EyeOffIcon() {
  return (
    <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="opacity-75">
      <path d="M9.88 9.88a3 3 0 1 0 4.24 4.24" />
      <path d="M10.73 5.08A10.43 10.43 0 0 1 12 5c7 0 10 7 10 7a13.16 13.16 0 0 1-1.67 2.68" />
      <path d="M6.61 6.61A13.52 13.52 0 0 0 2 12s3 7 10 7a9.74 9.74 0 0 0 5.39-1.61" />
      <line x1="2" y1="2" x2="22" y2="22" />
    </svg>
  );
}

function KeyValidationLine({ store, provider }: { readonly store: ApiKeysStore; readonly provider: KeyProvider }) {
  const state = useStore(store, (s) => s.validation[provider]);
  if (state.status === "idle") return null;

  if (state.status === "validating") {
    return (
      <span className="text-[var(--ink-secondary)] flex items-center gap-1" style={{ fontSize: "var(--text-meta-size)" }}>
        <svg className="animate-spin" style={{ width: 12, height: 12 }} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3">
          <circle cx="12" cy="12" r="10" stroke="currentColor" className="opacity-25" />
          <path d="M4 12a8 8 0 0 1 8-8" className="opacity-75" />
        </svg>
        Validating…
      </span>
    );
  }

  if (state.status === "valid") {
    return (
      <span
        className="font-medium flex items-center gap-1 text-[var(--success-text)]"
        style={{ fontSize: "var(--text-meta-size)" }}
      >
        <svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round">
          <polyline points="20 6 9 17 4 12" />
        </svg>
        Valid{state.latencyMs !== null ? ` (${state.latencyMs}ms)` : ""}
      </span>
    );
  }

  return (
    <span
      role="alert"
      className="font-medium flex items-center gap-1 text-[var(--error-text)]"
      style={{ fontSize: "var(--text-meta-size)" }}
    >
      <svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
        <line x1="18" y1="6" x2="6" y2="18" />
        <line x1="6" y1="6" x2="18" y2="18" />
      </svg>
      {state.message ?? "Invalid"}
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
  const [showDraft, setShowDraft] = useState(false);
  const required = REQUIRED_KEY_PROVIDERS.includes(provider);

  const save = async () => {
    const ok = await saveApiKey(store, vault, provider, draft);
    if (ok) setDraft("");
  };

  return (
    <div className="flex flex-col gap-[var(--space-1)] py-[var(--space-2)] border-b border-[var(--grey-50)] last:border-0">
      <div className="flex items-center justify-between">
        <label htmlFor={`key-${provider}`} className="font-semibold text-[var(--ink)]" style={{ fontSize: "var(--text-body-size)" }}>
          {KEY_PROVIDER_LABELS[provider]} {required ? <span className="text-[var(--ink-secondary)] font-normal text-[12px]">(required)</span> : <span className="text-[var(--ink-secondary)] font-normal text-[12px]">(optional)</span>}
        </label>
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
          className="flex items-center gap-[var(--space-2)] w-full"
          onSubmit={(e) => {
            e.preventDefault();
            void save();
          }}
        >
          <div className="flex-1 relative flex items-center">
            <input
              id={`key-${provider}`}
              type={showDraft ? "text" : "password"}
              autoComplete="off"
              aria-label={`${KEY_PROVIDER_LABELS[provider]} API key`}
              placeholder={`Paste ${KEY_PROVIDER_LABELS[provider]} key`}
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              className="w-full omni-input pr-[40px] text-[13px]"
            />
            <button
              type="button"
              onClick={() => setShowDraft(!showDraft)}
              className="absolute right-[var(--control-padding-x)] flex items-center justify-center p-1 rounded-md hover:bg-[var(--grey-50)] text-[var(--grey-600)]"
              style={{ border: "none", background: "none", cursor: "pointer" }}
            >
              {showDraft ? <EyeOffIcon /> : <EyeIcon />}
            </button>
          </div>
          <OmniButton variant="primary" small type="submit" disabled={saving || draft.length === 0}>
            {saving ? "Saving" : "Save"}
          </OmniButton>
        </form>
      )}
    </div>
  );
}

function CollapsibleSection({
  title,
  isOpen,
  onToggle,
  children,
}: {
  readonly title: string;
  readonly isOpen: boolean;
  readonly onToggle: () => void;
  readonly children: ReactNode;
}) {
  return (
    <div className="border border-[var(--grey-200)] rounded-[var(--radius-control)] overflow-hidden mb-[var(--space-3)]">
      <button
        type="button"
        onClick={onToggle}
        className="w-full flex items-center justify-between p-[var(--space-3)] bg-[var(--grey-50)] cursor-pointer text-left hover:bg-[var(--grey-100)] transition-colors border-none"
        style={{ outline: "none" }}
      >
        <span className="font-semibold text-[var(--ink)]" style={{ fontSize: "var(--text-body-size)" }}>
          {title}
        </span>
        <motion.svg
          xmlns="http://www.w3.org/2000/svg"
          width="16"
          height="16"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
          animate={{ rotate: isOpen ? 180 : 0 }}
          transition={{ duration: 0.18, ease: "easeInOut" }}
        >
          <polyline points="6 9 12 15 18 9" />
        </motion.svg>
      </button>
      <AnimatePresence initial={false}>
        {isOpen && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.2, ease: [0, 0, 0.2, 1] }}
            style={{ overflow: "hidden" }}
          >
            <div className="p-[var(--space-4)] bg-[var(--canvas)] border-t border-[var(--grey-200)]">
              {children}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

export function StepKeys({
  store,
  vault,
  validator,
  flowStore,
  onConnectGoogle,
}: {
  readonly store: ApiKeysStore;
  readonly vault: ApiKeyVault;
  readonly validator: KeyValidator;
  readonly flowStore: OnboardingFlowStore;
  readonly onConnectGoogle: (credentials?: {
    readonly clientId: string;
    readonly clientSecret: string;
  }) => void;
}) {
  const errorMessage = useStore(store, (s) => s.errorMessage);

  // Keep track of accordion states
  const [keysOpen, setKeysOpen] = useState(false);
  const [calendarOpen, setCalendarOpen] = useState(false);

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
        Finish & Optional Setup
      </h2>
      <p
        className="mt-[var(--space-2)] mb-[var(--space-6)] text-[var(--grey-600)]"
        style={{ fontSize: "var(--text-body-size)" }}
      >
        You are ready to use Omni Steroid. Optionally, configure API keys and integrations now, or skip and set them up later in Settings.
      </p>

      <div className="flex flex-col">
        {/* Collapsible Section 1: API Keys */}
        <CollapsibleSection
          title="API Keys (Optional)"
          isOpen={keysOpen}
          onToggle={() => {
            setKeysOpen(!keysOpen);
            if (calendarOpen) setCalendarOpen(false);
          }}
        >
          <div className="flex flex-col">
            <p className="m-0 mb-[var(--space-4)] text-[var(--ink-secondary)]" style={{ fontSize: 13 }}>
              Groq and Gemini power transcription enhancement and answers. Validate each to be sure it works.
            </p>
            {KEY_PROVIDERS.map((provider) => (
              <KeyEntryRow
                key={provider}
                store={store}
                vault={vault}
                validator={validator}
                provider={provider}
              />
            ))}
            {errorMessage !== null && (
              <p role="alert" className="m-0 mt-[var(--space-2)] text-[var(--error-text)]" style={{ fontSize: "var(--text-meta-size)" }}>
                {errorMessage}
              </p>
            )}
            <p className="m-0 mt-[var(--space-4)] text-[var(--ink-secondary)] font-normal" style={{ fontSize: 11 }}>
              Keys are encrypted with Windows DPAPI and never leave this device.
            </p>
          </div>
        </CollapsibleSection>

        {/* Collapsible Section 2: Calendar Integration */}
        <CollapsibleSection
          title="Calendar Integration (Optional)"
          isOpen={calendarOpen}
          onToggle={() => {
            setCalendarOpen(!calendarOpen);
            if (keysOpen) setKeysOpen(false);
          }}
        >
          <StepGoogleCalendar
            store={flowStore}
            onConnectGoogle={onConnectGoogle}
          />
        </CollapsibleSection>
      </div>
    </div>
  );
}
