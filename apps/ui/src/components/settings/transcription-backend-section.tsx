/**
 * Meetily-style transcription Settings: provider dropdown + downloadable
 * model cards (Parakeet core / Whisper ggml). Downloads use real
 * models.download events — never fake progress. Whisper rows delegate to
 * WhisperModelListSection to keep this file under the 300-line limit.
 */
import { useEffect, useState } from "react";
import { useStore } from "zustand";
import { Download } from "lucide-react";

import { SettingsGroupCard, SettingsRow } from "./settings-group-card";
import { WhisperModelListSection } from "./whisper-model-list-section";
import { updateSetting, type SettingsUpdater } from "../../lib/settings-actions";
import {
  cancelModelsDownload,
  deleteModelFile,
  getSetupStatus,
  startModelsDownload,
} from "../../lib/setup-settings-repository";
import {
  requestSetupCommand,
  subscribeToModelsDownload,
} from "../../lib/setup-settings-transport";
import { coreModelsCompleted, matchCompletedWhisperOption } from "../../lib/models-download-completion";
import { openModelsFolderAndReveal } from "../../lib/open-models-folder";
import { showToast } from "../../lib/toast-store";
import {
  DEFAULT_WHISPER_MODEL_ID,
  WHISPER_MODEL_OPTIONS,
} from "../../lib/whisper-model-catalog";
import type { SettingsStore } from "../../lib/settings-store";
import type { SetupModelStatus } from "../../lib/setup-settings-payloads";

type Provider = "parakeet" | "whisper" | "openai_compatible";

export function TranscriptionBackendSection({
  store,
  update = (partial) => updateSetting(store, partial),
}: {
  readonly store: SettingsStore;
  readonly update?: SettingsUpdater;
}) {
  const engine = useStore(store, (s) => s.settings?.sttEngine ?? "parakeet");
  const modelId = useStore(store, (s) => s.settings?.sttModelId ?? "");
  const baseUrl = useStore(store, (s) => s.settings?.sttOpenaiBaseUrl ?? "");
  // Local drafts so partial URLs / model ids do not round-trip mid-keystroke.
  const [modelIdDraft, setModelIdDraft] = useState(modelId);
  const [baseUrlDraft, setBaseUrlDraft] = useState(baseUrl);
  const [models, setModels] = useState<readonly SetupModelStatus[]>([]);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [coreBusy, setCoreBusy] = useState(false);
  const [downloadError, setDownloadError] = useState<string | null>(null);
  const [progress, setProgress] = useState<Record<string, { received: number; total: number | null }>>(
    {},
  );
  const [showAdvanced, setShowAdvanced] = useState(false);

  useEffect(() => {
    setModelIdDraft(modelId);
  }, [modelId]);
  useEffect(() => {
    setBaseUrlDraft(baseUrl);
  }, [baseUrl]);

  const persistModelId = (raw: string): void => {
    if (raw === modelId) return;
    void update({ sttModelId: raw });
  };
  const persistBaseUrl = (raw: string): void => {
    if (raw === baseUrl) return;
    void update({ sttOpenaiBaseUrl: raw });
  };

  const refresh = async (): Promise<void> => {
    try {
      setModels((await getSetupStatus()).models);
    } catch {
      /* best-effort */
    }
  };

  useEffect(() => {
    void refresh();
    return subscribeToModelsDownload({
      onProgress: (p) => {
        setProgress((prev) => ({
          ...prev,
          [p.file]: { received: p.receivedBytes, total: p.totalBytes },
        }));
      },
      onFailed: (f) => {
        setBusyId(null);
        setCoreBusy(false);
        setProgress({});
        setDownloadError(f.message || `Download failed for ${f.file}`);
      },
      onCompleted: (c) => {
        setBusyId(null);
        setCoreBusy(false);
        setProgress({});
        setDownloadError(null);
        void refresh();
        const whisperOpt = matchCompletedWhisperOption(c.files);
        if (whisperOpt !== null) {
          void update({ sttEngine: "whisper", sttModelId: whisperOpt.id });
          showToast(`${whisperOpt.label} is ready.`, "success");
        } else if (coreModelsCompleted(c.files)) {
          void update({ sttEngine: "parakeet", sttModelId: "" });
          showToast("Parakeet is ready.", "success");
        }
      },
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const corePresent =
    models.some((m) => m.file.includes("silero") && m.present) &&
    models.some((m) => m.file.includes("parakeet") && m.present);
  const presentFiles = new Set(models.filter((m) => m.present).map((m) => m.file));

  const selectProvider = (next: Provider): void => {
    if (next === "parakeet") {
      void update({ sttEngine: "parakeet", sttModelId: "" });
      return;
    }
    if (next === "whisper") {
      const id = WHISPER_MODEL_OPTIONS.some((o) => o.id === modelId)
        ? modelId
        : DEFAULT_WHISPER_MODEL_ID;
      void update({ sttEngine: "whisper", sttModelId: id });
      return;
    }
    void update({ sttEngine: "openai_compatible", sttModelId: modelId || "whisper-1" });
  };

  const downloadWhisper = async (id: string): Promise<void> => {
    setBusyId(id);
    setDownloadError(null);
    try {
      await startModelsDownload(requestSetupCommand, { bundle: "whisper", modelId: id });
    } catch (err) {
      setBusyId(null);
      setDownloadError(err instanceof Error ? err.message : "Could not start the download.");
    }
  };

  const downloadCore = async (): Promise<void> => {
    setCoreBusy(true);
    setDownloadError(null);
    try {
      await startModelsDownload(requestSetupCommand, { bundle: "core" });
    } catch (err) {
      setCoreBusy(false);
      setDownloadError(err instanceof Error ? err.message : "Could not start the download.");
    }
  };

  const cancelDownload = async (): Promise<void> => {
    try {
      await cancelModelsDownload();
    } catch {
      /* best-effort: the download may already be over */
    } finally {
      setBusyId(null);
      setCoreBusy(false);
      setProgress({});
    }
  };

  const deleteWhisper = async (file: string): Promise<void> => {
    setDownloadError(null);
    try {
      await deleteModelFile(file);
      await refresh();
    } catch (err) {
      setDownloadError(err instanceof Error ? err.message : "Could not delete the model file.");
    }
  };

  const openFolder = async (): Promise<void> => {
    try {
      await openModelsFolderAndReveal();
    } catch (err) {
      setDownloadError(err instanceof Error ? err.message : "Could not open the models folder.");
    }
  };

  return (
    <SettingsGroupCard label="Transcription">
      <SettingsRow
        title="Provider"
        subCaption="Live capture uses the selected on-device engine. Download a model before starting."
      >
        <select
          aria-label="Transcription provider"
          className="cursor-pointer border border-[var(--grey-300)] bg-[var(--canvas)] text-[var(--ink)]"
          style={{ height: 36, borderRadius: "var(--radius-control)", padding: "0 10px", fontSize: 13 }}
          value={engine}
          onChange={(e) => selectProvider(e.target.value as Provider)}
        >
          <option value="parakeet">Parakeet (Recommended)</option>
          <option value="whisper">Local Whisper</option>
          <option value="openai_compatible">Cloud STT</option>
        </select>
      </SettingsRow>

      {downloadError && (
        <p role="alert" className="m-0 mb-2 text-[var(--error-text)]" style={{ fontSize: 12 }}>
          {downloadError}
        </p>
      )}
      {(coreBusy || busyId !== null) && (
        <button
          type="button"
          onClick={() => void cancelDownload()}
          className="mb-2 cursor-pointer self-start border border-[var(--grey-300)] bg-[var(--canvas)] px-2 py-1 text-[var(--ink-secondary)]"
          style={{ borderRadius: "var(--radius-control)", fontSize: 12 }}
        >
          Cancel download
        </button>
      )}

      {engine === "parakeet" && (
        <div className="flex flex-col gap-2 pb-2">
          <div
            className="flex items-center justify-between gap-3 border px-3 py-2.5"
            style={{
              borderRadius: "var(--radius-control)",
              borderColor: corePresent ? "var(--accent)" : "var(--grey-200)",
              borderWidth: corePresent ? 2 : 1,
            }}
          >
            <div>
              <div className="text-[var(--ink)]" style={{ fontSize: 13, fontWeight: 600 }}>
                Parakeet TDT 0.6B
              </div>
              <div className="text-[var(--ink-secondary)]" style={{ fontSize: 12 }}>
                Fast on-device live transcription · Silero VAD included
              </div>
            </div>
            {corePresent ? (
              <span className="text-[var(--success-text)]" style={{ fontSize: 12 }}>
                Ready
              </span>
            ) : (
              <button
                type="button"
                disabled={coreBusy}
                onClick={() => void downloadCore()}
                className="flex cursor-pointer items-center gap-1 border border-[var(--grey-300)] bg-[var(--canvas)] px-2 py-1 disabled:opacity-60"
                style={{ borderRadius: "var(--radius-control)", fontSize: 12 }}
              >
                <Download size={12} />
                {coreBusy ? "…" : "Download"}
              </button>
            )}
          </div>
        </div>
      )}

      {engine === "whisper" && (
        <WhisperModelListSection
          modelId={modelId}
          presentFiles={presentFiles}
          progress={progress}
          busyId={busyId}
          showAdvanced={showAdvanced}
          onToggleAdvanced={() => setShowAdvanced((v) => !v)}
          onSelect={(id) => void update({ sttEngine: "whisper", sttModelId: id })}
          onDownload={(id) => void downloadWhisper(id)}
          onDelete={(file) => void deleteWhisper(file)}
        />
      )}

      {engine === "openai_compatible" && (
        <div className="flex flex-col gap-2 pb-2">
          <SettingsRow title="Cloud model id">
            <input
              aria-label="Cloud model id"
              className="omni-input w-full"
              style={{ height: "var(--control-height-sm)", paddingLeft: 8, paddingRight: 8 }}
              value={modelIdDraft}
              placeholder="whisper-1"
              onChange={(e) => setModelIdDraft(e.target.value)}
              onBlur={() => persistModelId(modelIdDraft)}
            />
          </SettingsRow>
          <SettingsRow title="Cloud endpoint" last>
            <input
              aria-label="Cloud endpoint"
              className="omni-input w-full"
              style={{ height: "var(--control-height-sm)", paddingLeft: 8, paddingRight: 8 }}
              value={baseUrlDraft}
              placeholder="https://api.openai.com/v1"
              onChange={(e) => setBaseUrlDraft(e.target.value)}
              onBlur={() => persistBaseUrl(baseUrlDraft)}
            />
          </SettingsRow>
        </div>
      )}

      <button
        type="button"
        onClick={() => void openFolder()}
        className="cursor-pointer self-start border border-[var(--grey-300)] bg-[var(--canvas)] px-2 py-1 text-[var(--ink-secondary)]"
        style={{ borderRadius: "var(--radius-control)", fontSize: 12 }}
      >
        Open models folder
      </button>
    </SettingsGroupCard>
  );
}
