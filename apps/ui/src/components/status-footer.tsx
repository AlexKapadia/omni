/**
 * Status footer: status dot, app version, uptime, live ping latency.
 *
 * The user explicitly wants real-time speed visible at all times, so the
 * latency readout stays a first-class element (this standing preference
 * overrides the rehaul's "hide latency" default). Rehaul v2 only changes the
 * typography: Inter (not mono) with tabular numerals, so the footer reads calm
 * instead of console-like. All data comes from the engine status store; this
 * component never touches the socket. Status is encoded as fill PLUS a text
 * label (never colour alone, for accessibility).
 */
import { motion, useReducedMotion } from "framer-motion";
import { tokenDurationSeconds } from "../lib/design-token-motion";
import { useEngineStatus } from "../lib/engine-status-store";
import type { EngineStatus } from "../lib/engine-status-store";
import { copy } from "../lib/copy";

// User-facing status copy (glossary: engineStatus). Human language, not
// architecture — "engine" is an implementation detail the user shouldn't need.
const STATUS_LABEL: Readonly<Record<EngineStatus, string>> = copy.engineStatus;

/** 3671 → "1h 1m 11s"; sub-minute stays compact ("42s"). */
export function formatUptime(uptimeS: number): string {
  const total = Math.floor(uptimeS);
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const seconds = total % 60;
  if (hours > 0) return `${hours}h ${minutes}m ${seconds}s`;
  if (minutes > 0) return `${minutes}m ${seconds}s`;
  return `${seconds}s`;
}

function StatusDot({ status }: { readonly status: EngineStatus }) {
  const reducedMotion = useReducedMotion();
  const fillClass =
    status === "connected"
      ? "bg-[var(--success)]"
      : status === "connecting"
        ? "bg-[var(--warning)]"
        : "bg-[var(--error)]";
  // Pulse period derives from the --dur-page token (no raw durations in
  // components); if the token is absent the duration is 0 and we skip the
  // animation entirely rather than divide the pulse into nothing.
  const pulseSeconds = tokenDurationSeconds("--dur-page") * 4;
  const shouldPulse = status === "connecting" && !reducedMotion && pulseSeconds > 0;
  return (
    <motion.span
      aria-hidden
      data-status={status}
      className={`inline-block h-1.5 w-1.5 rounded-full ${fillClass}`}
      // Gentle pulse only while connecting; static otherwise, and always
      // static under prefers-reduced-motion.
      animate={shouldPulse ? { opacity: [1, 0.3, 1] } : { opacity: 1 }}
      transition={shouldPulse ? { repeat: Infinity, duration: pulseSeconds } : { duration: 0 }}
    />
  );
}

export function StatusFooter() {
  const status = useEngineStatus((s) => s.status);
  const uptimeS = useEngineStatus((s) => s.uptimeS);
  const engineVersion = useEngineStatus((s) => s.engineVersion);
  const lastLatencyMs = useEngineStatus((s) => s.lastLatencyMs);
  const sttReady = useEngineStatus((s) => s.sttReady);
  const sttEngine = useEngineStatus((s) => s.sttEngine);
  const sttDevice = useEngineStatus((s) => s.sttDevice);

  return (
    <footer
      aria-label="Engine status"
      style={{ height: 36, padding: "0 var(--space-4)" }}
      className="flex shrink-0 items-center justify-between border-t border-[var(--grey-200)] font-[family-name:var(--font-label)] text-[var(--text-meta-size)] text-[var(--ink-secondary)] tabular-nums"
    >
      <span className="flex items-center gap-[var(--space-2)]">
        <StatusDot status={status} />
        <span aria-live="polite">{STATUS_LABEL[status]}</span>
      </span>
      <div className="flex items-center gap-[var(--space-4)]">
        {engineVersion !== null && <span>v{engineVersion}</span>}
        {status === "connected" && uptimeS !== null && <span>up {formatUptime(uptimeS)}</span>}
        {status === "connected" && sttReady && sttEngine !== null && (
          <span>
            stt {sttEngine}
            {sttDevice !== null ? `/${sttDevice}` : ""}
          </span>
        )}
        <span aria-label="Engine round-trip latency">
          {status === "connected" && lastLatencyMs !== null ? `${Math.round(lastLatencyMs)} ms` : "— ms"}
        </span>
      </div>
    </footer>
  );
}
