/**
 * The pill's 110×18 canvas waveform (20 bars) — design §8 exactly: 2.5px
 * ink bars on white, driven by REAL mic levels, attack 0.5 / decay 0.93,
 * floor 2px, idle level 0.06. Honors prefers-reduced-motion by rendering
 * the inactive baseline (no animation loop).
 */
import { useEffect, useRef } from "react";

import { openMicrophoneLevelSource, type MicrophoneLevelSource } from "./microphone-level-source";
import {
  BAR_WIDTH_PX,
  IDLE_FLOOR_LEVEL,
  PILL_WAVEFORM,
  barHeightPx,
  barTargetsFromTimeDomain,
  barXPx,
  stepBarLevel,
} from "./waveform-bar-levels";

const INK = "#0A0A0A";

function paintBars(context: CanvasRenderingContext2D, levels: readonly number[]): void {
  const { width, height, bars } = PILL_WAVEFORM;
  context.clearRect(0, 0, width, height);
  context.fillStyle = INK;
  for (let i = 0; i < bars; i += 1) {
    const barHeight = barHeightPx(levels[i] ?? IDLE_FLOOR_LEVEL, height);
    const y = (height - barHeight) / 2; // vertically centered
    context.fillRect(barXPx(i, width, bars), y, BAR_WIDTH_PX, barHeight);
  }
}

export function PillWaveformCanvas({ active }: { readonly active: boolean }) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (canvas === null) return;
    const context = canvas.getContext("2d");
    if (context === null) return;
    // Crisp on high-DPI: scale the backing store, draw in CSS pixels.
    const dpr = window.devicePixelRatio || 1;
    canvas.width = PILL_WAVEFORM.width * dpr;
    canvas.height = PILL_WAVEFORM.height * dpr;
    context.setTransform(dpr, 0, 0, dpr, 0, 0);

    const idleLevels = new Array<number>(PILL_WAVEFORM.bars).fill(IDLE_FLOOR_LEVEL);
    const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (!active || reducedMotion) {
      // Inactive/reduced-motion: the flat baseline, statically (§8).
      paintBars(context, idleLevels);
      return;
    }

    let mic: MicrophoneLevelSource | null = null;
    let frame = 0;
    let cancelled = false;
    const levels = [...idleLevels];
    const samples = new Uint8Array(128);

    const animate = () => {
      if (cancelled) return;
      const targets =
        mic !== null && mic.readTimeDomain(samples)
          ? barTargetsFromTimeDomain(samples, PILL_WAVEFORM.bars)
          : idleLevels; // mic unavailable: honest flat line, never fake levels
      for (let i = 0; i < levels.length; i += 1) {
        levels[i] = stepBarLevel(levels[i] ?? IDLE_FLOOR_LEVEL, targets[i] ?? IDLE_FLOOR_LEVEL);
      }
      paintBars(context, levels);
      frame = requestAnimationFrame(animate);
    };
    openMicrophoneLevelSource()
      .then((source) => {
        if (cancelled) {
          source.stop();
          return;
        }
        mic = source;
      })
      .catch(() => {
        mic = null; // permission denied: baseline stays flat (honest)
      });
    frame = requestAnimationFrame(animate);

    return () => {
      cancelled = true;
      cancelAnimationFrame(frame);
      mic?.stop();
    };
  }, [active]);

  return (
    <canvas
      ref={canvasRef}
      style={{ width: PILL_WAVEFORM.width, height: PILL_WAVEFORM.height, display: "block" }}
      aria-hidden="true"
    />
  );
}
