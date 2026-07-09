/**
 * Settings — Diagnostics (Advanced): a READ-ONLY view of the live engine
 * liveness the app already tracks — version, transcription device, uptime, and
 * round-trip latency. Every value is the REAL engine-status store (the same
 * source the status footer reads); nothing here is editable or invented, and a
 * value the engine has not reported yet renders an honest "—".
 */
import { useStore } from "zustand";
import { SettingsGroupCard, SettingsRow } from "./settings-group-card";
import {
  engineStatusStore,
  type EngineStatus,
  type EngineStatusStore,
} from "../../lib/engine-status-store";

// User-facing status copy (human language, not architecture — the user should
// never need to know there is an "engine" process).
const STATUS_LABEL: Readonly<Record<EngineStatus, string>> = {
  connecting: "Starting\u2026",
  connected: "Ready",
  disconnected: "Omni Steroid isn\u2019t running",
};

/** 3671 → "1h 1m 11s"; sub-minute stays compact ("42s"). */
function formatUptime(uptimeS: number): string {
  const total = Math.floor(uptimeS);
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const seconds = total % 60;
  if (hours > 0) return `${hours}h ${minutes}m ${seconds}s`;
  if (minutes > 0) return `${minutes}m ${seconds}s`;
  return `${seconds}s`;
}

function DiagnosticValue({ children }: { readonly children: string }) {
  return (
    <span className="text-[var(--ink-secondary)]" style={{ fontSize: "var(--text-meta-size)" }}>
      {children}
    </span>
  );
}

export function DiagnosticsSection({
  statusStore = engineStatusStore,
}: {
  readonly statusStore?: EngineStatusStore;
}) {
  const status = useStore(statusStore, (s) => s.status);
  const version = useStore(statusStore, (s) => s.engineVersion);
  const uptimeS = useStore(statusStore, (s) => s.uptimeS);
  const sttEngine = useStore(statusStore, (s) => s.sttEngine);
  const sttDevice = useStore(statusStore, (s) => s.sttDevice);
  const latencyMs = useStore(statusStore, (s) => s.lastLatencyMs);

  const transcriptionValue =
    sttEngine === null
      ? "—"
      : sttDevice === null
        ? sttEngine
        : `${sttEngine} · ${sttDevice}`;

  return (
    <SettingsGroupCard label="Diagnostics">
      <SettingsRow title="Status">
        <DiagnosticValue>{STATUS_LABEL[status]}</DiagnosticValue>
      </SettingsRow>
      <SettingsRow title="Omni Steroid version">
        <DiagnosticValue>{version === null ? "—" : `v${version}`}</DiagnosticValue>
      </SettingsRow>
      <SettingsRow title="Transcription device">
        <DiagnosticValue>{transcriptionValue}</DiagnosticValue>
      </SettingsRow>
      <SettingsRow title="Uptime">
        <DiagnosticValue>{uptimeS === null ? "—" : formatUptime(uptimeS)}</DiagnosticValue>
      </SettingsRow>
      <SettingsRow title="Round-trip latency" last>
        <DiagnosticValue>{latencyMs === null ? "—" : `${Math.round(latencyMs)} ms`}</DiagnosticValue>
      </SettingsRow>
    </SettingsGroupCard>
  );
}
