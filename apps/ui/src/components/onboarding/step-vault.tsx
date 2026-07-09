import { useStore } from "zustand";
import { OmniButton } from "../button";
import type { OnboardingFlowStore } from "../../lib/onboarding-flow-store";

export const DEFAULT_VAULT_PATH = "~/Documents/Omni Steroid";

export function StepVault({
  store,
  path,
  setPath,
  createNew,
  setCreateNew,
  onBrowse,
}: {
  readonly store: OnboardingFlowStore;
  readonly path: string;
  readonly setPath: (path: string) => void;
  readonly createNew: boolean;
  readonly setCreateNew: (create: boolean) => void;
  readonly onBrowse: () => void;
}) {
  const configured = useStore(store, (s) => s.vaultConfigured);
  const error = useStore(store, (s) => s.vaultError);
  const vaultPath = useStore(store, (s) => s.vaultPath);

  // Check if the current configured vault path matches our input
  const isConfigured = configured && path.trim() === (vaultPath ?? "").trim();

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
        Where should notes be saved?
      </h2>
      <p
        className="mt-[var(--space-2)] mb-0 text-[var(--grey-600)]"
        style={{ fontSize: "var(--text-body-size)" }}
      >
        Choose a folder on this device. Your meetings, transcripts, and enhanced notes all stay here.
      </p>

      {/* Path Display & Browse Button */}
      <div className="mt-[var(--space-6)] flex gap-[var(--space-2)] items-center">
        <div className="flex-1 relative flex items-center">
          <span className="absolute left-[var(--control-padding-x)] top-[12px] flex items-center justify-center pointer-events-none">
            <svg
              xmlns="http://www.w3.org/2000/svg"
              width="16"
              height="16"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
              style={{ color: "var(--ink-secondary)" }}
            >
              <path d="M20 20a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-7.9a2 2 0 0 1-1.69-.9L9.6 3.9A2 2 0 0 0 7.93 3H4a2 2 0 0 0-2 2v13a2 2 0 0 0 2 2Z" />
              <path d="M2 10h20" />
              <path d="m22 10-6 10H6L2 10" />
            </svg>
          </span>
          <input
            type="text"
            readOnly={typeof (window as any).__TAURI__ !== "undefined"}
            className="w-full omni-input pl-[40px] select-all cursor-default text-[13px]"
            value={path}
            onChange={(e) => setPath(e.target.value)}
            placeholder="No folder selected"
          />
        </div>
        <OmniButton variant="secondary" onClick={onBrowse}>
          Choose folder
        </OmniButton>
      </div>

      {/* Create-new toggle */}
      <div className="mt-[var(--space-6)] flex items-start gap-[var(--space-3)]">
        <input
          id="create-new-folder-checkbox"
          type="checkbox"
          checked={createNew}
          onChange={(e) => setCreateNew(e.target.checked)}
          className="mt-1 h-4 w-4 rounded border-[var(--grey-300)] text-[var(--accent)] focus:ring-[var(--accent)]"
        />
        <div className="flex flex-col gap-[var(--space-1)]">
          <label
            htmlFor="create-new-folder-checkbox"
            className="font-medium text-[var(--ink)] cursor-pointer"
            style={{ fontSize: "var(--text-body-size)" }}
          >
            Create this folder
          </label>
          <span className="text-[var(--ink-secondary)]" style={{ fontSize: "var(--text-meta-size)" }}>
            If it does not exist, Omni Steroid will create it automatically.
          </span>
        </div>
      </div>

      {/* Success / Error Banners */}
      {isConfigured && (
        <div
          className="mt-[var(--space-6)] p-[var(--space-3)] rounded-[var(--radius-control)] bg-[var(--success-bg)] border border-[var(--success)] flex items-center gap-[var(--space-2)]"
          style={{ color: "var(--success-text)" }}
        >
          <svg
            xmlns="http://www.w3.org/2000/svg"
            width="16"
            height="16"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="3"
            strokeLinecap="round"
            strokeLinejoin="round"
          >
            <polyline points="20 6 9 17 4 12" />
          </svg>
          <span className="font-medium" style={{ fontSize: "var(--text-body-size)" }}>
            Notes folder configured
          </span>
        </div>
      )}

      {error && (
        <div
          className="mt-[var(--space-6)] p-[var(--space-3)] rounded-[var(--radius-control)] bg-[var(--error-bg)] border border-[var(--error)] flex items-start gap-[var(--space-2)]"
          style={{ color: "var(--error-text)" }}
        >
          <svg
            xmlns="http://www.w3.org/2000/svg"
            width="16"
            height="16"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
            className="mt-0.5 shrink-0"
          >
            <circle cx="12" cy="12" r="10" />
            <line x1="12" y1="8" x2="12" y2="12" />
            <line x1="12" y1="16" x2="12.01" y2="16" />
          </svg>
          <span style={{ fontSize: "var(--text-body-size)" }}>
            {error}
          </span>
        </div>
      )}
    </div>
  );
}
