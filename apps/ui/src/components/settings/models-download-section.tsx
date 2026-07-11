/**
 * On-device core models (Silero VAD + Parakeet) — driven by setup.status +
 * models.download. Whisper sizes live under Transcription engine.
 */
import { useEffect, useState } from "react";
import { Download } from "lucide-react";

import { SettingsGroupCard } from "./settings-group-card";
import { getSetupStatus, startModelsDownload } from "../../lib/setup-settings-repository";
import { requestSetupCommand, subscribeToModelsDownload } from "../../lib/setup-settings-transport";
import { isCoreSttStatusFile } from "../../lib/whisper-model-catalog";
import type { SetupStatus } from "../../lib/setup-settings-payloads";

interface FileProgress {
  readonly received: number;
  readonly total: number | null;
}

export function ModelsDownloadSection() {
  const [status, setStatus] = useState<SetupStatus | null>(null);
  const [statusError, setStatusError] = useState<string | null>(null);
  const [downloadError, setDownloadError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [progress, setProgress] = useState<Record<string, FileProgress>>({});

  const refresh = async (): Promise<void> => {
    try {
      const next = await getSetupStatus();
      setStatus(next);
      setStatusError(null);
    } catch (err) {
      setStatusError(err instanceof Error ? err.message : "Could not read model status.");
    }
  };

  useEffect(() => {
    void refresh();
    return subscribeToModelsDownload({
      onProgress: (p) => {
        if (!isCoreSttStatusFile(p.file)) return;
        setProgress((prev) => ({
          ...prev,
          [p.file]: { received: p.receivedBytes, total: p.totalBytes },
        }));
      },
      onFailed: (f) => {
        if (!isCoreSttStatusFile(f.file) && f.file !== "") return;
        setBusy(false);
        setProgress({});
        setDownloadError(f.message || `Download failed for ${f.file}`);
      },
      onCompleted: () => {
        setBusy(false);
        setProgress({});
        setDownloadError(null);
        void refresh();
      },
    });
  }, []);

  const models = (status?.models ?? []).filter((m) => isCoreSttStatusFile(m.file));
  const allPresent = models.length > 0 && models.every((m) => m.present);

  const onDownload = async (): Promise<void> => {
    setBusy(true);
    setDownloadError(null);
    setProgress({});
    try {
      await startModelsDownload(requestSetupCommand, { bundle: "core" });
    } catch (err) {
      setBusy(false);
      setDownloadError(err instanceof Error ? err.message : "Could not start the download.");
    }
  };

  return (
    <SettingsGroupCard label="Live capture models">
      <div className="flex flex-col gap-3">
        <p className="m-0 text-[var(--ink-secondary)]" style={{ fontSize: "var(--text-body-size)" }}>
          Silero VAD and Parakeet for live meetings. Whisper downloads are under Transcription engine.
        </p>

        {statusError && (
          <p role="alert" className="m-0 text-[var(--error-text)]" style={{ fontSize: 13 }}>
            {statusError}
          </p>
        )}
        {downloadError && (
          <p role="alert" className="m-0 text-[var(--error-text)]" style={{ fontSize: 13 }}>
            {downloadError}
          </p>
        )}

        {models.length === 0 && !statusError && (
          <p className="m-0 text-[var(--ink-secondary)]" style={{ fontSize: 13 }}>
            Waiting for the engine to report which models are installed…
          </p>
        )}

        <ul className="m-0 flex list-none flex-col gap-2 p-0">
          {models.map((model) => {
            const fileProgress = progress[model.file];
            const pct =
              fileProgress && fileProgress.total && fileProgress.total > 0
                ? Math.min(100, Math.round((fileProgress.received / fileProgress.total) * 100))
                : null;
            return (
              <li
                key={model.file}
                className="flex items-center justify-between gap-3 rounded-[var(--radius-control)] border border-[var(--grey-200)] bg-[var(--surface)] px-3 py-2"
              >
                <div className="min-w-0 flex flex-col">
                  <span className="truncate font-[family-name:var(--font-mono)] text-[var(--ink)]" style={{ fontSize: 12 }}>
                    {model.file}
                  </span>
                  <span className="text-[var(--ink-secondary)]" style={{ fontSize: 12 }}>
                    {model.present ? "Installed" : fileProgress ? "Downloading…" : "Not installed"}
                  </span>
                </div>
                {fileProgress ? (
                  <div className="flex w-28 flex-col items-end gap-1">
                    <span className="text-[var(--accent)]" style={{ fontSize: 11 }}>
                      {pct !== null ? `${pct}%` : "…"}
                    </span>
                    <div className="h-1.5 w-full overflow-hidden rounded-full bg-[var(--grey-200)]">
                      <div
                        className="h-full bg-[var(--accent)] transition-all duration-300"
                        style={{ width: pct !== null ? `${pct}%` : "30%" }}
                      />
                    </div>
                  </div>
                ) : (
                  <span
                    className={model.present ? "text-[var(--success-text)]" : "text-[var(--ink-secondary)]"}
                    style={{ fontSize: 12 }}
                  >
                    {model.present ? "Ready" : "Missing"}
                  </span>
                )}
              </li>
            );
          })}
        </ul>

        {!allPresent && (
          <button
            type="button"
            disabled={busy}
            onClick={() => void onDownload()}
            className="flex cursor-pointer items-center gap-2 self-start rounded-[var(--radius-control)] border border-[var(--grey-300)] bg-[var(--surface)] px-3 py-2 text-[var(--ink)] hover:bg-[var(--grey-50)] disabled:cursor-not-allowed disabled:opacity-60"
            style={{ fontSize: 13 }}
          >
            <Download size={14} />
            {busy ? "Downloading…" : "Download missing models"}
          </button>
        )}
      </div>
    </SettingsGroupCard>
  );
}
