/**
 * Settings — Software update: listens for the shell's updater events and
 * drives download/install + restart. Quiet non-blocking notice on error
 * (offline / no release is not fatal).
 */
import { invoke } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";
import { useEffect, useRef, useState } from "react";
import { SettingsGroupCard, SettingsRow } from "./settings-group-card";

export interface UpdateAvailableInfo {
  readonly version: string;
  readonly currentVersion: string;
  readonly notes: string | null;
}

type UpdaterPhase =
  | "idle"
  | "available"
  | "downloading"
  | "installed"
  | "error";

function isPlainObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function parseUpdateAvailable(payload: unknown): UpdateAvailableInfo | null {
  if (!isPlainObject(payload)) return null;
  const version = payload["version"];
  const currentVersion = payload["currentVersion"];
  const notes = payload["notes"];
  if (typeof version !== "string" || version.length === 0) return null;
  if (typeof currentVersion !== "string") return null;
  if (notes !== null && notes !== undefined && typeof notes !== "string") return null;
  return {
    version,
    currentVersion,
    notes: typeof notes === "string" ? notes : null,
  };
}

function parseProgress(payload: unknown): { downloaded: number; total: number | null } | null {
  if (!isPlainObject(payload)) return null;
  const downloaded = payload["downloadedBytes"];
  const total = payload["totalBytes"];
  if (typeof downloaded !== "number" || !Number.isFinite(downloaded)) return null;
  if (total !== null && total !== undefined && typeof total !== "number") return null;
  return {
    downloaded,
    total: typeof total === "number" ? total : null,
  };
}

export function UpdaterSection() {
  const [phase, setPhase] = useState<UpdaterPhase>("idle");
  const [update, setUpdate] = useState<UpdateAvailableInfo | null>(null);
  const [progress, setProgress] = useState<{ downloaded: number; total: number | null } | null>(
    null,
  );
  const [errorNotice, setErrorNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const phaseRef = useRef<UpdaterPhase>(phase);
  phaseRef.current = phase;

  useEffect(() => {
    let cancelled = false;
    const unlisteners: Array<() => void> = [];
    void (async () => {
      try {
        unlisteners.push(
          await listen("updater:update-available", (event) => {
            if (cancelled) return;
            const parsed = parseUpdateAvailable(event.payload);
            if (parsed === null) return;
            setUpdate(parsed);
            setPhase("available");
            setErrorNotice(null);
          }),
        );
        unlisteners.push(
          await listen("updater:download-progress", (event) => {
            if (cancelled) return;
            const parsed = parseProgress(event.payload);
            if (parsed !== null) setProgress(parsed);
          }),
        );
        unlisteners.push(
          await listen("updater:installed", () => {
            if (cancelled) return;
            setPhase("installed");
            setBusy(false);
          }),
        );
        unlisteners.push(
          await listen("updater:error", (event) => {
            if (cancelled) return;
            // Quiet non-blocking notice — offline / missing release is not fatal.
            const message =
              isPlainObject(event.payload) && typeof event.payload["message"] === "string"
                ? event.payload["message"]
                : "Update check failed";
            setErrorNotice(message);
            if (phaseRef.current === "downloading") {
              setPhase("error");
              setBusy(false);
            }
          }),
        );
      } catch {
        // Web build / tests: no Tauri shell.
      }
    })();
    return () => {
      cancelled = true;
      for (const unlisten of unlisteners) unlisten();
    };
  }, []);

  const install = (): void => {
    setBusy(true);
    setPhase("downloading");
    setProgress(null);
    setErrorNotice(null);
    void invoke("updater_download_and_install")
      .then(() => {
        setPhase("installed");
        setBusy(false);
      })
      .catch((error: unknown) => {
        setPhase("error");
        setBusy(false);
        setErrorNotice(error instanceof Error ? error.message : String(error));
      });
  };

  const restart = (): void => {
    void invoke("updater_restart_app").catch((error: unknown) => {
      setErrorNotice(error instanceof Error ? error.message : String(error));
    });
  };

  const progressLabel =
    progress === null
      ? "Downloading…"
      : progress.total !== null && progress.total > 0
        ? `Downloading… ${Math.min(100, Math.round((progress.downloaded / progress.total) * 100))}%`
        : `Downloading… ${Math.round(progress.downloaded / 1024)} KB`;

  return (
    <SettingsGroupCard label="Software update">
      {phase === "idle" && errorNotice === null && (
        <SettingsRow title="Status" last>
          <span className="text-[var(--ink-secondary)]" style={{ fontSize: "var(--text-meta-size)" }}>
            Omni checks for updates when it starts.
          </span>
        </SettingsRow>
      )}
      {phase === "available" && update !== null && (
        <SettingsRow
          title={`Version ${update.version} available`}
          subCaption={`You have ${update.currentVersion}`}
          last
        >
          <button
            type="button"
            className="cursor-pointer rounded-[var(--radius-control)] bg-[var(--accent)] px-3 py-1.5 text-xs font-semibold text-[var(--on-accent)]"
            onClick={install}
            disabled={busy}
          >
            Install update
          </button>
        </SettingsRow>
      )}
      {phase === "downloading" && (
        <SettingsRow title="Installing" last>
          <span className="text-[var(--ink-secondary)]" style={{ fontSize: "var(--text-meta-size)" }}>
            {progressLabel}
          </span>
        </SettingsRow>
      )}
      {phase === "installed" && (
        <SettingsRow title="Update installed" subCaption="Restart to finish" last>
          <button
            type="button"
            className="cursor-pointer rounded-[var(--radius-control)] bg-[var(--accent)] px-3 py-1.5 text-xs font-semibold text-[var(--on-accent)]"
            onClick={restart}
          >
            Restart now
          </button>
        </SettingsRow>
      )}
      {errorNotice !== null && phase !== "available" && phase !== "installed" && (
        <SettingsRow title="Update notice" last>
          <span className="text-[var(--ink-secondary)]" style={{ fontSize: "var(--text-meta-size)" }}>
            {errorNotice}
          </span>
        </SettingsRow>
      )}
    </SettingsGroupCard>
  );
}
