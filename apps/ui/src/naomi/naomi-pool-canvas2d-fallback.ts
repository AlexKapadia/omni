/**
 * Tier 3 / Tier 4 pool: the Canvas2D analytic fallback (brief §1 ladder) —
 * rim = base radius + 3 summed harmonics + audio envelope, interior = 3
 * layered radial gradients in brief greys, ≤2ms/frame. Tier 4 is exactly one
 * static frame of this drawing (reduced-motion base state / zero-GPU path).
 *
 * Same design language as the shader: ink body, #525252 inner currents,
 * 1.5px ink meniscus, faint #EDEDED wet edge — so a machine with no GPU
 * still meets Naomi, not a spinner.
 */

import type { PoolPhysics } from "./naomi-affect-parameter-mapper";
import type { AudioFrameFeatures } from "./naomi-pool-uniforms";

const INK = "#0A0A0A";
const GREY_200 = "#EDEDED";
// Interior currents use rgba(82,82,82,…) literals below — #525252 with the
// brief's 8–14% alpha mixed in.

/** Rim radius at angle θ: analytic harmonics stand in for the shader's FBM. */
export function analyticRimRadius(
  theta: number,
  timeSeconds: number,
  physics: PoolPhysics,
  envelope: number,
): number {
  const breathe = physics.breatheDepth * Math.sin((timeSeconds * 2 * Math.PI) / 2.4);
  const amp =
    physics.rimAmplitude *
    (1 - physics.audioCoupling + physics.audioCoupling * envelope);
  const f = physics.rimNoiseFrequency;
  // Three incommensurate harmonics drifting at different rates — a cheap,
  // deterministic stand-in for FBM that never visibly repeats.
  const harmonics =
    0.5 * Math.sin(theta * Math.round(3 * f) + timeSeconds * (0.3 + physics.flowSpeed)) +
    0.3 * Math.sin(theta * Math.round(5 * f) - timeSeconds * (0.23 + 0.7 * physics.flowSpeed)) +
    0.2 * Math.sin(theta * Math.round(7 * f) + timeSeconds * (0.17 + 1.3 * physics.flowSpeed));
  return physics.radiusBias * (1 + breathe) + amp * harmonics;
}

/**
 * Draw one frame. `radiusPx` is R=1 in canvas pixels; the caller owns canvas
 * sizing and the rAF loop (or calls this exactly once for Tier 4).
 */
export function drawAnalyticPoolFrame(
  ctx: CanvasRenderingContext2D,
  widthPx: number,
  heightPx: number,
  radiusPx: number,
  timeSeconds: number,
  physics: PoolPhysics,
  audio: AudioFrameFeatures,
  errorState: boolean,
): void {
  ctx.clearRect(0, 0, widthPx, heightPx);
  const cx = widthPx / 2;
  const cy = heightPx / 2 - physics.restOffset * radiusPx;

  // Rim path from the analytic radius, sampled at 96 spokes.
  const SPOKES = 96;
  ctx.beginPath();
  for (let i = 0; i <= SPOKES; i++) {
    const theta = (i / SPOKES) * 2 * Math.PI;
    const r = analyticRimRadius(theta, timeSeconds, physics, audio.envelope) * radiusPx;
    const x = cx + Math.cos(theta) * r;
    const y = cy + Math.sin(theta) * r;
    if (i === 0) ctx.moveTo(x, y);
    else ctx.lineTo(x, y);
  }
  ctx.closePath();

  // Faint wet edge just outside the body (brief: #EDEDED ring on white).
  ctx.save();
  ctx.strokeStyle = GREY_200;
  ctx.lineWidth = radiusPx * 0.06;
  ctx.globalAlpha = 0.7;
  ctx.stroke();
  ctx.restore();

  // Body fill: ink base with three layered radial gradients suggesting the
  // interior currents (the shader's grey bands, analytically).
  const baseR = physics.radiusBias * radiusPx;
  const fill = ctx.createRadialGradient(cx, cy, baseR * 0.1, cx, cy, baseR);
  fill.addColorStop(0, INK);
  fill.addColorStop(1, INK);
  ctx.fillStyle = fill;
  ctx.fill();

  const drift = timeSeconds * physics.flowSpeed;
  for (let layer = 0; layer < 3; layer++) {
    const angle = drift * (0.6 + 0.3 * layer) + (layer * 2 * Math.PI) / 3;
    const ox = Math.cos(angle) * baseR * 0.35;
    const oy = Math.sin(angle) * baseR * 0.35;
    const current = ctx.createRadialGradient(
      cx + ox, cy + oy, 0,
      cx + ox, cy + oy, baseR * (0.55 + 0.15 * layer),
    );
    // Currents in #525252 at 8–14% — the shader's exact mix range.
    current.addColorStop(0, "rgba(82, 82, 82, 0.14)");
    current.addColorStop(1, "rgba(82, 82, 82, 0)");
    ctx.save();
    ctx.clip(); // currents exist only inside the pool
    ctx.fillStyle = current;
    ctx.fillRect(cx - baseR, cy - baseR, baseR * 2, baseR * 2);
    ctx.restore();
  }

  // Meniscus rim line: 1.5px ink, 2px in the error state.
  ctx.strokeStyle = INK;
  ctx.lineWidth = errorState ? 2 : 1.5;
  ctx.stroke();
}
