/**
 * Settings — Notes folder (Essentials): shows the REAL vault directory from
 * settings.get and lets the user point Omni at a different folder.
 *
 * Wiring is real end-to-end: the folder picker is the same Tauri dialog seam
 * the onboarding vault step uses, and the chosen path persists through the REAL
 * settings.update (vault_dir). The engine validates the folder and may reject —
 * its message is shown verbatim (fail closed, never an assumed OK).
 */
import { useState } from "react";
import { useStore } from "zustand";
import { OmniButton } from "../button";
import { SettingsGroupCard, SettingsRow } from "./settings-group-card";
import { pickVaultDirectory } from "../../lib/pick-vault-directory";
import type { SettingsStore } from "../../lib/settings-store";
import type { SettingsUpdater } from "../../lib/settings-actions";

export function NotesFolderSection({
  store,
  update,
  pick = pickVaultDirectory,
}: {
  readonly store: SettingsStore;
  readonly update: SettingsUpdater;
  /** Injectable folder picker (defaults to the real Tauri dialog seam). */
  readonly pick?: () => Promise<string | null>;
}) {
  const vaultDir = useStore(store, (s) => s.settings?.vaultDir ?? null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const change = async (): Promise<void> => {
    setBusy(true);
    setError(null);
    try {
      const path = await pick();
      if (path === null || path.trim().length === 0) return; // cancelled — no change
      const result = await update({ vaultDir: path.trim() });
      if (!result.ok) setError(result.message);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not open the folder picker.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <SettingsGroupCard label="Notes folder">
      <SettingsRow
        title="Vault folder"
        subCaption={vaultDir ?? "No folder chosen yet — Omni Steroid reads and writes your notes here."}
        last={error === null}
      >
        <OmniButton
          variant="secondary"
          small
          disabled={busy}
          aria-label="Change notes folder"
          onClick={() => void change()}
        >
          {busy ? "Choosing…" : "Change"}
        </OmniButton>
      </SettingsRow>
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
