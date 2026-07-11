/**
 * Whisper ggml model rows: presence/progress, select-when-present, download,
 * and delete-when-installed. Extracted from transcription-backend-section.tsx
 * to keep that file under the 300-line limit.
 */
import { Download, Trash2 } from "lucide-react";
import { WHISPER_MODEL_OPTIONS, formatWhisperSize, whisperStatusFile } from "../../lib/whisper-model-catalog";

interface FileProgress {
  readonly received: number;
  readonly total: number | null;
}

export function WhisperModelListSection({
  modelId,
  presentFiles,
  progress,
  busyId,
  showAdvanced,
  onToggleAdvanced,
  onSelect,
  onDownload,
  onDelete,
}: {
  readonly modelId: string;
  readonly presentFiles: ReadonlySet<string>;
  readonly progress: Readonly<Record<string, FileProgress>>;
  readonly busyId: string | null;
  readonly showAdvanced: boolean;
  readonly onToggleAdvanced: () => void;
  readonly onSelect: (id: string) => void;
  readonly onDownload: (id: string) => void;
  readonly onDelete: (file: string) => void;
}) {
  const basic = WHISPER_MODEL_OPTIONS.filter((o) => o.basic);
  const advanced = WHISPER_MODEL_OPTIONS.filter((o) => !o.basic);
  const visible = showAdvanced ? [...basic, ...advanced] : basic;

  return (
    <div className="flex flex-col gap-2 pb-2">
      {visible.map((opt) => {
        const file = whisperStatusFile(opt.id);
        const present = presentFiles.has(file);
        const selected = modelId === opt.id;
        const fileProgress = progress[file];
        const pct =
          fileProgress?.total && fileProgress.total > 0
            ? Math.min(100, Math.round((fileProgress.received / fileProgress.total) * 100))
            : null;
        return (
          <div
            key={opt.id}
            className="flex flex-wrap items-center justify-between gap-2 border px-3 py-2"
            style={{
              borderRadius: "var(--radius-control)",
              borderColor: selected && present ? "var(--accent)" : "var(--grey-200)",
              borderWidth: selected && present ? 2 : 1,
              cursor: present ? "pointer" : "default",
            }}
            onClick={() => {
              if (present) onSelect(opt.id);
            }}
            onKeyDown={(e) => {
              if (present && (e.key === "Enter" || e.key === " ")) {
                e.preventDefault();
                onSelect(opt.id);
              }
            }}
            role={present ? "button" : undefined}
            tabIndex={present ? 0 : undefined}
          >
            <div className="min-w-0">
              <div className="text-[var(--ink)]" style={{ fontSize: 13 }}>
                {opt.label}
                {selected && present ? " · in use" : ""}
              </div>
              <div className="text-[var(--ink-secondary)]" style={{ fontSize: 12 }}>
                {opt.detail} · {formatWhisperSize(opt.sizeMb)}
                {present ? " · Ready" : fileProgress ? " · Downloading…" : ""}
              </div>
              {fileProgress && (
                <div className="mt-1 h-1.5 w-40 overflow-hidden rounded-full bg-[var(--grey-200)]">
                  <div
                    className="h-full bg-[var(--accent)]"
                    style={{ width: pct !== null ? `${pct}%` : "30%" }}
                  />
                </div>
              )}
            </div>
            {present ? (
              <button
                type="button"
                onClick={(e) => {
                  e.stopPropagation();
                  onDelete(file);
                }}
                aria-label={`Delete ${opt.label}`}
                className="flex cursor-pointer items-center gap-1 border border-[var(--grey-300)] bg-[var(--canvas)] px-2 py-1 text-[var(--error-text)]"
                style={{ borderRadius: "var(--radius-control)", fontSize: 12 }}
              >
                <Trash2 size={12} />
              </button>
            ) : (
              <button
                type="button"
                disabled={busyId !== null}
                onClick={(e) => {
                  e.stopPropagation();
                  onDownload(opt.id);
                }}
                className="flex cursor-pointer items-center gap-1 border border-[var(--grey-300)] bg-[var(--canvas)] px-2 py-1 disabled:opacity-60"
                style={{ borderRadius: "var(--radius-control)", fontSize: 12 }}
              >
                <Download size={12} />
                {busyId === opt.id ? "…" : "Download"}
              </button>
            )}
          </div>
        );
      })}
      <button
        type="button"
        className="cursor-pointer self-start text-[var(--ink-secondary)] underline"
        style={{ fontSize: 12, background: "none", border: "none", padding: 0 }}
        onClick={onToggleAdvanced}
      >
        {showAdvanced ? "Hide advanced models" : "Advanced models"}
      </button>
      <p className="m-0 text-[var(--ink-secondary)]" style={{ fontSize: 12 }}>
        ggml models from Hugging Face (same catalog as Meetily). Requires{" "}
        <code>uv sync --extra whisper</code>.
      </p>
    </div>
  );
}
