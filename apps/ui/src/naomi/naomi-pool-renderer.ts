/**
 * The Naomi pool renderer: owns the canvas, the render tier (probe →
 * fallback ladder), devicePixelRatio-aware sizing, the rAF loop with
 * visibility pause, the performance governor, and per-frame uniform packing.
 *
 * Render is stateless by contract: each frame draws purely from
 * (time, audioFeatures, smoothedAffect) — this class only carries the
 * orchestration state (tier, sizes, clocks), never simulation memory.
 * Reduced motion (brief §6): NO loop — exactly one still frame per state
 * change, frozen time, resting envelope.
 */

import {
  createAffectSmoother,
  ERROR_STATE_PHYSICS,
  mapAffectToPoolPhysics,
  type PoolPhysics,
} from "./naomi-affect-parameter-mapper";
import { IDLE_AFFECT, type Affect } from "./naomi-affect-types";
import { drawAnalyticPoolFrame } from "./naomi-pool-canvas2d-fallback";
import {
  createUniformValues,
  packNaomiUniforms,
  SILENT_AUDIO_FEATURES,
  type AudioFrameFeatures,
} from "./naomi-pool-uniforms";
import { NaomiPerformanceGovernor } from "./naomi-performance-governor";
import { chooseRenderTier, probeRenderCapabilities, type RenderTier } from "./naomi-render-tier-ladder";
import { createPoolGlProgram, drawPoolGlFrame, type PoolGlProgram } from "./naomi-webgl-program";

/** Live readout for the dev tuning drawer (speed showcase mandate). */
export interface RendererStats {
  readonly tier: RenderTier;
  readonly fps: number;
  readonly renderScale: number;
  readonly p95FrameMs: number | null;
}

/** Supplies per-frame audio features (the playback/mic analyser tap). */
export type AudioFeatureSampler = (attack: number, decay: number) => AudioFrameFeatures;

export class NaomiPoolRenderer {
  private readonly canvas: HTMLCanvasElement;
  private tier: RenderTier;
  private glProgram: PoolGlProgram | null = null;
  private ctx2d: CanvasRenderingContext2D | null = null;
  private readonly governor = new NaomiPerformanceGovernor();
  private readonly uniforms = createUniformValues();
  private smoother = createAffectSmoother(IDLE_AFFECT);
  private targetAffect: Affect = IDLE_AFFECT;
  private errorState = false;
  private burstSeed = 0;
  private reducedMotion: boolean;
  private audioSampler: AudioFeatureSampler | null = null;
  private rafHandle: number | null = null;
  private running = false;
  private lastFrameMs: number | null = null;
  private timeSeconds = 0;
  private cssWidth = 0;
  private cssHeight = 0;
  private frameParity = 0;
  private fpsEstimate = 0;
  // Reused every frame — the rAF loop's zero-allocation budget (brief §5).
  private readonly packingFlags = { reducedMotion: false, errorState: false, burstSeed: 0 };

  constructor(canvas: HTMLCanvasElement, reducedMotion: boolean) {
    this.canvas = canvas;
    this.reducedMotion = reducedMotion;
    // Probe → decide → construct, falling one tier at a time (fail closed:
    // a compile failure on real WebGL2 hardware still lands on Canvas2D).
    this.tier = chooseRenderTier(probeRenderCapabilities());
    if (this.tier === 1 || this.tier === 2) {
      this.glProgram = createPoolGlProgram(canvas, this.tier);
      if (this.glProgram === null) this.tier = 3;
    }
    if (this.tier >= 3) {
      this.ctx2d = canvas.getContext("2d");
      if (this.ctx2d === null) this.tier = 4;
    }
    if (reducedMotion && this.tier === 3) this.tier = 4; // still pool = one frame
  }

  get stats(): RendererStats {
    return {
      tier: this.tier,
      fps: Math.round(this.fpsEstimate),
      renderScale: this.governor.quality.renderScale,
      p95FrameMs: this.governor.p95Ms,
    };
  }

  /** Update the affect target; a new laugh burst reseeds droplet orbits. */
  setAffect(affect: Affect): void {
    const newBurst = affect.burst !== null && this.targetAffect.burst === null;
    if (newBurst) this.burstSeed = (this.burstSeed + 0.6180339887) % 1;
    this.targetAffect = affect;
    if (this.reducedMotion) this.drawStillFrame(); // redraw on state change only
  }

  setErrorState(errorState: boolean): void {
    this.errorState = errorState;
    if (this.reducedMotion) this.drawStillFrame();
  }

  /** Connect/disconnect the live analyser tap driving the water. */
  setAudioSampler(sampler: AudioFeatureSampler | null): void {
    this.audioSampler = sampler;
  }

  /** CSS size changed (ResizeObserver, debounced by the view). */
  resize(cssWidth: number, cssHeight: number, devicePixelRatio: number): void {
    this.cssWidth = cssWidth;
    this.cssHeight = cssHeight;
    // Brief §4: buffer = css × min(dpr, 2) × renderScale from the governor.
    const scale = Math.min(devicePixelRatio, 2) * this.governor.quality.renderScale;
    this.canvas.width = Math.max(1, Math.round(cssWidth * scale));
    this.canvas.height = Math.max(1, Math.round(cssHeight * scale));
    if (this.reducedMotion) this.drawStillFrame();
  }

  start(): void {
    if (this.reducedMotion) {
      this.drawStillFrame(); // Tier 4 semantics: exactly one frame, no loop
      return;
    }
    if (this.running) return;
    this.running = true;
    const loop = (nowMs: number) => {
      if (!this.running) return;
      this.rafHandle = requestAnimationFrame(loop);
      // Visibility pause: rAF stops firing in background tabs by itself;
      // the dt clamp below also absorbs any long gap on resume.
      const rawDt = this.lastFrameMs === null ? 16.7 : nowMs - this.lastFrameMs;
      this.lastFrameMs = nowMs;
      const dtMs = Math.min(rawDt, 100);
      this.fpsEstimate = this.fpsEstimate * 0.9 + (1000 / Math.max(dtMs, 1)) * 0.1;
      const qualityChanged = this.governor.recordFrame(dtMs, nowMs);
      if (qualityChanged) this.resize(this.cssWidth, this.cssHeight, window.devicePixelRatio);
      // 30fps cap with time dilation: draw alternate frames, halve motion
      // speed so per-drawn-frame travel stays constant (smooth, slower).
      const quality = this.governor.quality;
      this.frameParity ^= 1;
      const timeScale = quality.fpsCap === 30 ? 0.5 : 1;
      this.timeSeconds += (dtMs / 1000) * timeScale;
      if (quality.fpsCap === 30 && this.frameParity === 1) return;
      this.renderFrame(dtMs / 1000);
    };
    this.rafHandle = requestAnimationFrame(loop);
  }

  stop(): void {
    this.running = false;
    if (this.rafHandle !== null) cancelAnimationFrame(this.rafHandle);
    this.rafHandle = null;
    this.lastFrameMs = null;
  }

  private currentPhysics(dtSeconds: number): PoolPhysics {
    if (this.errorState) return ERROR_STATE_PHYSICS;
    const smoothed = this.smoother.step(this.targetAffect, dtSeconds);
    return mapAffectToPoolPhysics(smoothed);
  }

  private renderFrame(dtSeconds: number): void {
    const physics = this.currentPhysics(dtSeconds);
    const audio =
      this.audioSampler === null
        ? SILENT_AUDIO_FEATURES
        : this.audioSampler(physics.envelopeAttack, physics.envelopeDecay);
    this.draw(this.timeSeconds, physics, audio);
  }

  private drawStillFrame(): void {
    // Reduced motion: frozen t, resting envelope — the state's end pose,
    // drawn immediately with no tweening (brief §6).
    const physics = this.errorState
      ? ERROR_STATE_PHYSICS
      : mapAffectToPoolPhysics(this.targetAffect);
    this.draw(0, physics, SILENT_AUDIO_FEATURES);
  }

  private draw(timeSeconds: number, physics: PoolPhysics, audio: AudioFrameFeatures): void {
    const width = this.canvas.width;
    const height = this.canvas.height;
    if (width === 0 || height === 0) return;
    // Pool radius in device px: the pool diameter is 1/1.6 of the canvas
    // (headroom for rim displacement + detached droplets at ~1.5R).
    const poolRadiusPx = Math.min(width, height) / (2 * 1.6);
    if (this.glProgram !== null && (this.tier === 1 || this.tier === 2)) {
      this.packingFlags.reducedMotion = this.reducedMotion;
      this.packingFlags.errorState = this.errorState;
      this.packingFlags.burstSeed = this.burstSeed;
      packNaomiUniforms(this.uniforms, timeSeconds, audio, physics, this.packingFlags);
      // Governor octave cap applied post-pack: uniforms-only, no allocation.
      this.uniforms.flow[3] = Math.min(physics.octaves, this.governor.quality.octaveCap);
      drawPoolGlFrame(this.glProgram, this.uniforms, width, height, poolRadiusPx);
      return;
    }
    if (this.ctx2d !== null) {
      drawAnalyticPoolFrame(
        this.ctx2d, width, height, poolRadiusPx,
        this.reducedMotion ? 0 : timeSeconds, physics, audio, this.errorState,
      );
    }
  }
}
