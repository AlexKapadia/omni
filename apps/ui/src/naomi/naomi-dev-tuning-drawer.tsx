/**
 * Naomi development tuning drawer: collapsible, monochrome, token-styled
 * controls for driving the pool live — emotion presets, valence/arousal
 * sliders, mic toggle, the say/cancel voice loop, and the FPS + tier
 * readout (the speed-showcase mandate).
 *
 * Purely presentational: every control calls back into NaomiView, which owns
 * the renderer, socket, and audio graph. Nothing here is decorative — every
 * element is wired to real behaviour.
 */

import { useState } from "react";
import type { RendererStats } from "./naomi-pool-renderer";

export interface NaomiPresetDefinition {
  readonly id: string;
  readonly label: string;
  readonly valence: number;
  readonly arousal: number;
  readonly laugh: boolean;
}

/** The four named dev presets (brief table rows). */
export const NAOMI_DEV_PRESETS: readonly NaomiPresetDefinition[] = [
  { id: "idle", label: "Idle", valence: 0, arousal: 0.1, laugh: false },
  { id: "happy", label: "Happy", valence: 0.7, arousal: 0.6, laugh: false },
  { id: "laughing", label: "Laughing", valence: 0.8, arousal: 0.85, laugh: true },
  { id: "agitated", label: "Agitated", valence: -0.6, arousal: 0.9, laugh: false },
];

export interface NaomiDevTuningDrawerProps {
  readonly valence: number;
  readonly arousal: number;
  readonly onAffectChange: (valence: number, arousal: number, laugh: boolean) => void;
  readonly micEnabled: boolean;
  readonly onMicToggle: () => void;
  readonly stats: RendererStats | null;
  readonly engineConnected: boolean;
  readonly ttfaMs: number | null;
  readonly speaking: boolean;
  readonly lastError: string | null;
  readonly onSay: (text: string) => void;
  readonly onCancel: () => void;
}

const labelStyle: React.CSSProperties = {
  fontFamily: "var(--font-mono)",
  fontSize: 11,
  letterSpacing: "var(--label-ls)",
  textTransform: "uppercase",
  color: "var(--grey-400)",
};

const monoValueStyle: React.CSSProperties = {
  fontFamily: "var(--font-mono)",
  fontSize: "var(--text-meta-size)",
  color: "var(--grey-600)",
};

export function NaomiDevTuningDrawer(props: NaomiDevTuningDrawerProps) {
  const [open, setOpen] = useState(true);
  const [sayText, setSayText] = useState("");

  const submitSay = () => {
    const text = sayText.trim();
    if (text.length > 0) props.onSay(text);
  };

  return (
    <aside
      aria-label="Naomi development tuning"
      className="border-t border-[var(--grey-200)] bg-[var(--canvas)]"
      style={{ padding: open ? "16px 48px 20px" : "8px 48px" }}
    >
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        className="cursor-pointer border-none bg-transparent p-0"
        style={labelStyle}
      >
        {open ? "▾ Tuning" : "▸ Tuning"}
      </button>
      {open && (
        <div className="mt-[var(--space-3)] flex flex-wrap items-end gap-[var(--space-8)]">
          <div>
            <p className="m-0 mb-[var(--space-2)]" style={labelStyle}>Emotion</p>
            <div className="flex gap-[var(--space-2)]">
              {NAOMI_DEV_PRESETS.map((preset) => (
                <button
                  key={preset.id}
                  type="button"
                  onClick={() => props.onAffectChange(preset.valence, preset.arousal, preset.laugh)}
                  className="cursor-pointer border border-[var(--grey-300)] bg-transparent text-[var(--ink)] hover:border-[var(--ink)]"
                  style={{
                    padding: "6px 12px",
                    borderRadius: "var(--radius-control)",
                    fontSize: 13,
                    fontFamily: "var(--font-body)",
                  }}
                >
                  {preset.label}
                </button>
              ))}
            </div>
          </div>
          <div className="flex flex-col gap-[var(--space-2)]">
            <label className="flex items-center gap-[var(--space-3)]" style={labelStyle}>
              Valence
              <input
                type="range" min={-1} max={1} step={0.01} value={props.valence}
                onChange={(e) => props.onAffectChange(Number(e.target.value), props.arousal, false)}
                style={{ accentColor: "var(--ink)", width: 160 }}
              />
              <span style={monoValueStyle}>{props.valence.toFixed(2)}</span>
            </label>
            <label className="flex items-center gap-[var(--space-3)]" style={labelStyle}>
              Arousal
              <input
                type="range" min={0} max={1} step={0.01} value={props.arousal}
                onChange={(e) => props.onAffectChange(props.valence, Number(e.target.value), false)}
                style={{ accentColor: "var(--ink)", width: 160 }}
              />
              <span style={monoValueStyle}>{props.arousal.toFixed(2)}</span>
            </label>
          </div>
          <div>
            <p className="m-0 mb-[var(--space-2)]" style={labelStyle}>Mic drive</p>
            <button
              type="button"
              onClick={props.onMicToggle}
              aria-pressed={props.micEnabled}
              className={
                "cursor-pointer border bg-transparent " +
                (props.micEnabled
                  ? "border-[var(--ink)] font-medium text-[var(--ink)]"
                  : "border-[var(--grey-300)] text-[var(--grey-600)]")
              }
              style={{ padding: "6px 12px", borderRadius: "var(--radius-control)", fontSize: 13 }}
            >
              {props.micEnabled ? "Mic live" : "Mic off"}
            </button>
          </div>
          <div className="flex min-w-[420px] flex-1 flex-col gap-[var(--space-2)]">
            <p className="m-0" style={labelStyle}>
              Say {props.engineConnected ? "" : "· engine offline"}
            </p>
            <div className="flex gap-[var(--space-2)]">
              <input
                type="text"
                value={sayText}
                placeholder="Type a sentence for Naomi to speak…"
                onChange={(e) => setSayText(e.target.value)}
                onKeyDown={(e) => { if (e.key === "Enter") submitSay(); }}
                className="min-w-0 flex-1 border border-[var(--grey-300)] bg-transparent text-[var(--ink)] outline-none focus:border-[var(--ink)]"
                style={{ padding: "8px 12px", borderRadius: "var(--radius-control)", fontSize: 14 }}
              />
              <button
                type="button"
                onClick={submitSay}
                disabled={!props.engineConnected || sayText.trim().length === 0}
                className="cursor-pointer border-none bg-[var(--ink)] text-[var(--canvas)] disabled:cursor-default disabled:bg-[var(--grey-300)]"
                style={{ padding: "8px 16px", borderRadius: "var(--radius-control)", fontSize: 13 }}
              >
                Say
              </button>
              <button
                type="button"
                onClick={props.onCancel}
                disabled={!props.speaking}
                className="cursor-pointer border border-[var(--grey-300)] bg-transparent text-[var(--grey-600)] disabled:cursor-default disabled:text-[var(--grey-300)]"
                style={{ padding: "8px 12px", borderRadius: "var(--radius-control)", fontSize: 13 }}
              >
                Cancel
              </button>
            </div>
            {props.lastError !== null && (
              <p className="m-0" style={{ ...monoValueStyle, color: "var(--ink)" }}>
                {props.lastError}
              </p>
            )}
          </div>
          <div style={monoValueStyle} data-testid="naomi-stats-readout">
            <p className="m-0" style={labelStyle}>Render</p>
            <p className="m-0">
              tier {props.stats?.tier ?? "—"} · {props.stats?.fps ?? "—"} fps · scale{" "}
              {props.stats?.renderScale ?? "—"}
              {props.stats?.p95FrameMs != null && ` · p95 ${props.stats.p95FrameMs.toFixed(1)}ms`}
            </p>
            <p className="m-0">
              {props.ttfaMs !== null ? `ttfa ${Math.round(props.ttfaMs)}ms` : "ttfa —"}
              {props.speaking ? " · speaking" : ""}
            </p>
          </div>
        </div>
      )}
    </aside>
  );
}
