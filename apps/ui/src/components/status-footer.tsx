/**
 * Status footer: engine status dot, engine version, uptime, live ping latency.
 *
 * The user explicitly wants real-time engine speed visible at all times, so the
 * latency readout is a first-class element, not a debug afterthought. All data
 * comes from the engine status store; this component never touches the socket.
 * Monochrome by contract — status is encoded as ink/grey fill plus a text
 * label (never colour alone, for accessibility).
 */
import { motion, useReducedMotion } from "framer-motion";
import { tokenDurationSeconds } from "../lib/design-token-motion";
import { useEngineStatus } from "../lib/engine-status-store";
import type { EngineStatus } from "../lib/engine-status-store";

const STATUS_LABEL: Readonly<Record<EngineStatus, string>> = {
  connecting: "connecting to engine",
  connected: "engine running",
  disconnected: "engine unavailable",
};

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
      ? "bg-[var(--ink)]"
      : status === "connecting"
        ? "bg-[var(--grey-400)]"
        : "border border-[var(--grey-400)] bg-[var(--canvas)]";
  // Pulse period derives from the --dur-page token (no raw durations in
  // components); if the token is absent the duration is 0 and we skip the
  // animation entirely rather than divide the pulse into nothing.
  const pulseSeconds = tokenDurationSeconds("--dur-page") * 4;
  const shouldPulse = status === "connecting" && !reducedMotion && pulseSeconds > 0;
  return (
    <motion.span
      aria-hidden
      data-status={status}
      className={`inline-block h-2 w-2 rounded-full ${fillClass}`}
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

  return (
    <footer
      aria-label="Engine status"
      className="flex shrink-0 items-center gap-[var(--space-4)] border-t border-[var(--grey-200)] px-[var(--space-4)] py-[var(--space-2)] font-[family-name:var(--font-mono)] text-xs text-[var(--grey-600)]"
    >
      <span className="flex items-center gap-[var(--space-2)]">
        <StatusDot status={status} />
        <span aria-live="polite">{STATUS_LABEL[status]}</span>
      </span>
      {engineVersion !== null && <span>v{engineVersion}</span>}
      {status === "connected" && uptimeS !== null && <span>up {formatUptime(uptimeS)}</span>}
      <span className="ml-auto" aria-label="Engine round-trip latency">
        {status === "connected" && lastLatencyMs !== null ? `${Math.round(lastLatencyMs)} ms` : "— ms"}
      </span>
    </footer>
  );
}
