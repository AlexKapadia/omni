import type { ModelFileProgress } from "../../lib/onboarding-flow-store";

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${Math.max(0, Math.floor(bytes))} B`;
  const kb = bytes / 1024;
  if (kb < 1024) return `${kb.toFixed(0)} KB`;
  const mb = kb / 1024;
  if (mb < 1024) return `${mb.toFixed(1)} MB`;
  return `${(mb / 1024).toFixed(2)} GB`;
}

export function OnboardingModelProgressRow({ file }: { readonly file: ModelFileProgress }) {
  const pct =
    file.totalBytes !== null && file.totalBytes > 0
      ? Math.min(100, Math.max(0, (file.receivedBytes / file.totalBytes) * 100))
      : 0;
  const failed = file.failedMessage !== null;

  let statusText = "";
  if (failed) {
    statusText = file.failedMessage || "Download failed";
  } else if (file.totalBytes === null) {
    statusText = `${formatBytes(file.receivedBytes)} downloading`;
  } else {
    const done = file.totalBytes > 0 && file.receivedBytes >= file.totalBytes;
    if (done && file.sha256Verified === true) {
      statusText = "✓ Verified";
    } else if (done) {
      statusText = "Verifying…";
    } else {
      statusText = `${formatBytes(file.receivedBytes)} / ${formatBytes(file.totalBytes)} (${pct.toFixed(0)}%)`;
    }
  }

  return (
    <div className="flex flex-col gap-[var(--space-1)] py-[var(--space-2)]">
      <div className="flex items-center justify-between gap-[var(--space-3)]">
        <span
          className="truncate font-[family-name:var(--font-mono)] text-[var(--ink)]"
          style={{ fontSize: "var(--text-meta-size)" }}
        >
          {file.file}
        </span>
        <span
          className={`shrink-0 font-[family-name:var(--font-mono)] ${failed ? "text-[var(--error-text)]" : "text-[var(--ink-secondary)]"}`}
          style={{ fontSize: "var(--text-meta-size)" }}
          role={failed ? "alert" : undefined}
        >
          {statusText}
        </span>
      </div>
      <div className="w-full omni-progress-track">
        <div
          className="omni-progress-fill"
          style={{
            transform: `scaleX(${pct / 100})`,
            background: failed ? "var(--error)" : "var(--track-fill)",
          }}
        />
      </div>
    </div>
  );
}
