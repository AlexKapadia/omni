/**
 * One model file's REAL download row: name, bytes, a token-styled progress bar
 * (track grey-200, fill ink, 4px, pill radius) whose fill is received/total,
 * and the sha256-verified check when the engine confirms integrity. A failed
 * file shows the engine's message; retry lives at the step level.
 */
import type { ModelFileProgress } from "../../lib/onboarding-flow-store";

/** Bytes → a compact "12.3 MB" label. Display only, never used for math. */
function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${Math.max(0, Math.floor(bytes))} B`;
  const kb = bytes / 1024;
  if (kb < 1024) return `${kb.toFixed(0)} KB`;
  const mb = kb / 1024;
  if (mb < 1024) return `${mb.toFixed(1)} MB`;
  return `${(mb / 1024).toFixed(2)} GB`;
}

function fractionText(file: ModelFileProgress): string {
  if (file.failedMessage !== null) return file.failedMessage;
  if (file.totalBytes === null) return `${formatBytes(file.receivedBytes)} downloading`;
  const done = file.totalBytes > 0 && file.receivedBytes >= file.totalBytes;
  if (done && file.sha256Verified === true) return "✓ verified";
  if (done) return "verifying";
  return `${formatBytes(file.receivedBytes)} / ${formatBytes(file.totalBytes)}`;
}

export function OnboardingModelProgressRow({ file }: { readonly file: ModelFileProgress }) {
  const pct =
    file.totalBytes !== null && file.totalBytes > 0
      ? Math.min(100, Math.max(0, (file.receivedBytes / file.totalBytes) * 100))
      : 0;
  const failed = file.failedMessage !== null;
  return (
    <div className="flex flex-col gap-[var(--space-1)]" style={{ padding: "8px 0" }}>
      <div className="flex items-center justify-between gap-[var(--space-3)]">
        <span
          className="truncate font-[family-name:var(--font-mono)] text-[var(--grey-600)]"
          style={{ fontSize: "var(--text-meta-size)" }}
        >
          {file.file}
        </span>
        <span
          className={`shrink-0 font-[family-name:var(--font-mono)] ${failed ? "text-[var(--grey-600)]" : "text-[var(--grey-400)]"}`}
          style={{ fontSize: "var(--text-meta-size)" }}
          role={failed ? "alert" : undefined}
        >
          {fractionText(file)}
        </span>
      </div>
      <div
        aria-hidden
        className="w-full overflow-hidden bg-[var(--grey-200)]"
        style={{ height: 4, borderRadius: "var(--radius-pill)" }}
      >
        <div
          className="h-full bg-[var(--ink)]"
          style={{
            width: `${pct}%`,
            borderRadius: "var(--radius-pill)",
            transition: "width var(--dur-panel) var(--ease-out)",
          }}
        />
      </div>
    </div>
  );
}
