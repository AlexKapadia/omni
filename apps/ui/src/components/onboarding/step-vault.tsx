/**
 * Onboarding step 2 — choose the vault folder. The user browses with the Tauri
 * dialog OR types a path, optionally asking Omni to create a new vault folder.
 * The path is persisted through the REAL settings.update; the engine validates
 * writability and MAY reject — its message is shown verbatim (fail closed).
 */
import { useEffect, useState } from "react";
import { useStore } from "zustand";
import { OmniButton } from "../button";
import { ToggleSwitch } from "../toggle-switch";
import type { OnboardingFlowStore } from "../../lib/onboarding-flow-store";

export function StepVault({
  store,
  onBrowse,
  onUseFolder,
}: {
  readonly store: OnboardingFlowStore;
  readonly onBrowse: () => void;
  readonly onUseFolder: (path: string, createNew: boolean) => void;
}) {
  const vaultPath = useStore(store, (s) => s.vaultPath);
  const configured = useStore(store, (s) => s.vaultConfigured);
  const busy = useStore(store, (s) => s.vaultBusy);
  const error = useStore(store, (s) => s.vaultError);
  const [path, setPath] = useState(vaultPath ?? "");
  const [createNew, setCreateNew] = useState(false);

  // A path chosen via the Tauri picker lands in the store — mirror it here.
  useEffect(() => {
    if (vaultPath !== null) setPath(vaultPath);
  }, [vaultPath]);

  const ready = configured && path.trim() === (vaultPath ?? "").trim() && path.trim().length > 0;

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
        Choose your vault
      </h2>
      <p
        className="mt-[var(--space-2)] mb-0 text-[var(--grey-600)]"
        style={{ fontSize: "var(--text-body-size)" }}
      >
        Omni reads and writes notes here — your Obsidian vault, or a fresh folder.
      </p>

      <div
        className="mt-[var(--space-6)] flex items-center gap-[var(--space-2)] border"
        style={{
          borderColor: ready ? "var(--ink)" : "var(--grey-300)",
          borderRadius: "var(--radius-card)",
          padding: "10px 12px",
        }}
      >
        <input
          aria-label="Vault folder path"
          placeholder="~/Documents/vault or C:\\Users\\you\\vault"
          value={path}
          onChange={(e) => setPath(e.target.value)}
          className="min-w-0 flex-1 border-none bg-transparent font-[family-name:var(--font-mono)] text-[var(--ink)] outline-none placeholder:text-[var(--grey-300)]"
          style={{ fontSize: "var(--text-transcript-size)" }}
        />
        <OmniButton variant="ghost" small onClick={onBrowse}>
          Browse
        </OmniButton>
      </div>

      <div className="mt-[var(--space-4)] flex items-center justify-between gap-[var(--space-3)]">
        <div className="flex min-w-0 flex-col gap-[var(--space-1)]">
          <span className="text-[var(--ink)]" style={{ fontSize: "var(--text-body-size)" }}>
            Create a new vault here
          </span>
          <span className="text-[var(--ink-secondary)]" style={{ fontSize: "var(--text-meta-size)" }}>
            makes the folder if it does not exist yet
          </span>
        </div>
        <ToggleSwitch
          checked={createNew}
          onChange={setCreateNew}
          label="Create a new vault here"
        />
      </div>

      {ready && (
        <p
          className="mt-[var(--space-4)] mb-0 font-medium text-[var(--ink)]"
          style={{ fontSize: "var(--text-meta-size)" }}
        >
          ✓ folder ready
        </p>
      )}
      {error !== null && (
        <p
          role="alert"
          className="mt-[var(--space-4)] mb-0 text-[var(--grey-600)]"
          style={{ fontSize: "var(--text-meta-size)" }}
        >
          {error}
        </p>
      )}

      <div className="mt-auto flex justify-end pt-[var(--space-6)]">
        <OmniButton
          variant="primary"
          disabled={busy || path.trim().length === 0}
          onClick={() => onUseFolder(path.trim(), createNew)}
        >
          {busy ? "Checking folder" : ready ? "Folder set" : "Use this folder"}
        </OmniButton>
      </div>
    </div>
  );
}
