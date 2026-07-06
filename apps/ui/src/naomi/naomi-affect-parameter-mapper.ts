/**
 * The Naomi emotion engine: continuous (valence, arousal, burst) → pool
 * physics parameters, per the brief's emotion→physics table
 * (docs/design/naomi-visual-brief.md §2).
 *
 * WHY interpolation instead of the brief's illustrative linear laws: the
 * brief declares "the table rows are the canonical checkpoints these
 * formulas must reproduce (test fixture)", but its linear sketches
 * (e.g. flowSpeed = 0.04 + 0.46a) do NOT pass through the table rows
 * (idle a=0.1 gives 0.086, table says 0.04). The table is the contract, so
 * the continuous field here is inverse-distance-weighted (Shepard, p=2)
 * interpolation over the eight named (v, a) anchors — EXACT at every
 * checkpoint by construction, smooth and continuous everywhere between,
 * never a discrete switch. Burst blends the field toward the Laughing
 * anchor by intensity. Pure and deterministic: same triple, same physics.
 */

import { type Affect, burstIntensity } from "./naomi-affect-types";

/** Every physical quality the shader consumes, as closed-form numbers. */
export interface PoolPhysics {
  /** Curl-advection speed, pool radii per second. */
  readonly flowSpeed: number;
  /** FBM frequency along the rim angle. */
  readonly rimNoiseFrequency: number;
  /** FBM frequency of the interior flow field. */
  readonly interiorNoiseFrequency: number;
  /** FBM octaves (fractional between anchors; shader fades the last octave). */
  readonly octaves: number;
  /** Rim displacement amplitude, ×R (before any audio envelope). */
  readonly rimAmplitude: number;
  /** 0..1: how much the live audio envelope multiplies rimAmplitude. */
  readonly audioCoupling: number;
  /** Quadratic smin surface-tension k, ×R. Low k → droplets neck off. */
  readonly surfaceTension: number;
  /** Audio envelope attack coefficient (per-frame lerp toward target). */
  readonly envelopeAttack: number;
  /** Audio envelope decay multiplier (per-frame). */
  readonly envelopeDecay: number;
  /** Base radius multiplier. */
  readonly radiusBias: number;
  /** Breathing sine depth (2400ms period — the house heartbeat). */
  readonly breatheDepth: number;
  /** Vertical bob: depth (×R) and frequency (Hz) — happy buoyancy. */
  readonly bobDepth: number;
  readonly bobFrequencyHz: number;
  /** Concentric ring pulses: depth and rate (Hz) — laughter syllables. */
  readonly ringPulseDepth: number;
  readonly ringPulseFrequencyHz: number;
  /** Irregular micro-jitter: amplitude (×R) and rate (Hz) — agitation. */
  readonly jitterAmplitude: number;
  readonly jitterFrequencyHz: number;
  /** Radial inward drift bias added to flow — thinking's slow spiral. */
  readonly inwardDriftBias: number;
  /** Vertical rest offset ×R (sad pool "sits lower"). */
  readonly restOffset: number;
  /** Detached satellite droplets (0–4), integer. */
  readonly dropletCount: number;
}

type PhysicsRow = Omit<PoolPhysics, "dropletCount"> & { readonly dropletCount: number };

interface Anchor {
  readonly name: string;
  readonly valence: number;
  readonly arousal: number;
  readonly row: PhysicsRow;
}

function row(overrides: Partial<PhysicsRow> & Pick<PhysicsRow,
  "flowSpeed" | "rimNoiseFrequency" | "interiorNoiseFrequency" | "octaves" |
  "rimAmplitude" | "surfaceTension" | "envelopeAttack" | "envelopeDecay" | "radiusBias"
>): PhysicsRow {
  return {
    audioCoupling: 0,
    breatheDepth: 0,
    bobDepth: 0,
    bobFrequencyHz: 0,
    ringPulseDepth: 0,
    ringPulseFrequencyHz: 0,
    jitterAmplitude: 0,
    jitterFrequencyHz: 0,
    inwardDriftBias: 0,
    restOffset: 0,
    dropletCount: 0,
    ...overrides,
  };
}

/**
 * The brief's table, verbatim where specified. Unspecified cells (e.g.
 * breatheDepth outside idle) are on-device tuning values, which the brief
 * §8 explicitly leaves to the build phase.
 */
export const EMOTION_ANCHORS: readonly Anchor[] = [
  { name: "idle", valence: 0, arousal: 0.1, row: row({
    flowSpeed: 0.04, rimNoiseFrequency: 1.2, interiorNoiseFrequency: 1.6, octaves: 3,
    rimAmplitude: 0.015, surfaceTension: 0.30, envelopeAttack: 0.25, envelopeDecay: 0.97,
    radiusBias: 1.0, breatheDepth: 0.015 }) },
  { name: "listening", valence: 0, arousal: 0.35, row: row({
    flowSpeed: 0.12, rimNoiseFrequency: 1.4, interiorNoiseFrequency: 1.8, octaves: 3,
    rimAmplitude: 0.03, audioCoupling: 1, surfaceTension: 0.28, envelopeAttack: 0.5,
    envelopeDecay: 0.93, radiusBias: 1.02, breatheDepth: 0.006 }) },
  { name: "thinking", valence: 0.1, arousal: 0.45, row: row({
    flowSpeed: 0.18, rimNoiseFrequency: 1.0, interiorNoiseFrequency: 2.2, octaves: 4,
    rimAmplitude: 0.02, surfaceTension: 0.26, envelopeAttack: 0.3, envelopeDecay: 0.96,
    radiusBias: 0.98, inwardDriftBias: 0.05, breatheDepth: 0.008 }) },
  { name: "speaking", valence: 0.1, arousal: 0.5, row: row({
    flowSpeed: 0.25, rimNoiseFrequency: 1.5, interiorNoiseFrequency: 2.0, octaves: 4,
    rimAmplitude: 0.05, audioCoupling: 1, surfaceTension: 0.25, envelopeAttack: 0.5,
    envelopeDecay: 0.93, radiusBias: 1.02 }) },
  { name: "happy", valence: 0.7, arousal: 0.6, row: row({
    flowSpeed: 0.32, rimNoiseFrequency: 1.0, interiorNoiseFrequency: 1.6, octaves: 3,
    rimAmplitude: 0.06, audioCoupling: 1, surfaceTension: 0.34, envelopeAttack: 0.5,
    envelopeDecay: 0.94, radiusBias: 1.06, bobDepth: 0.02, bobFrequencyHz: 0.3 }) },
  { name: "laughing", valence: 0.8, arousal: 0.85, row: row({
    flowSpeed: 0.38, rimNoiseFrequency: 1.3, interiorNoiseFrequency: 1.8, octaves: 4,
    rimAmplitude: 0.08, surfaceTension: 0.20, envelopeAttack: 0.7, envelopeDecay: 0.90,
    radiusBias: 1.04, ringPulseDepth: 0.08, ringPulseFrequencyHz: 5, dropletCount: 3 }) },
  { name: "agitated", valence: -0.6, arousal: 0.9, row: row({
    flowSpeed: 0.50, rimNoiseFrequency: 2.8, interiorNoiseFrequency: 3.2, octaves: 5,
    rimAmplitude: 0.07, surfaceTension: 0.06, envelopeAttack: 0.8, envelopeDecay: 0.85,
    radiusBias: 0.97, jitterAmplitude: 0.012, jitterFrequencyHz: 10 }) },
  { name: "sad", valence: -0.5, arousal: 0.15, row: row({
    flowSpeed: 0.06, rimNoiseFrequency: 0.9, interiorNoiseFrequency: 1.4, octaves: 3,
    rimAmplitude: 0.012, surfaceTension: 0.32, envelopeAttack: 0.2, envelopeDecay: 0.98,
    radiusBias: 0.96, restOffset: -0.02, breatheDepth: 0.01 }) },
];

/**
 * The error / fail-closed pool (brief table's last row): a discrete SYSTEM
 * state, not a point on the affect field — exposed as its own constant.
 * Rim line weight doubles to 2px (handled by the renderer's error flag).
 */
export const ERROR_STATE_PHYSICS: PoolPhysics = row({
  flowSpeed: 0.05, rimNoiseFrequency: 1.2, interiorNoiseFrequency: 1.6, octaves: 3,
  rimAmplitude: 0.01, surfaceTension: 0.30, envelopeAttack: 0.25, envelopeDecay: 0.97,
  radiusBias: 0.95,
});

// The Laughing anchor doubles as the burst-blend target (brief: droplets
// detach, tension drops). Found by name so a table reorder cannot break it.
const LAUGHING_ROW: PhysicsRow = (() => {
  const anchor = EMOTION_ANCHORS.find((a) => a.name === "laughing");
  if (anchor === undefined) throw new Error("laughing anchor missing from the emotion table");
  return anchor.row;
})();

const PHYSICS_KEYS = Object.keys(LAUGHING_ROW) as ReadonlyArray<keyof PhysicsRow>;

// Below this squared distance an affect point IS an anchor: return the row
// verbatim (avoids the 1/d² singularity and guarantees checkpoint exactness).
const ANCHOR_SNAP_DISTANCE_SQ = 1e-12;

/** Shepard inverse-distance-weighted blend of the anchor rows at (v, a). */
function interpolateAnchors(valence: number, arousal: number): PhysicsRow {
  const weights: number[] = [];
  for (const anchor of EMOTION_ANCHORS) {
    const dv = valence - anchor.valence;
    const da = arousal - anchor.arousal;
    const distSq = dv * dv + da * da;
    if (distSq < ANCHOR_SNAP_DISTANCE_SQ) return anchor.row; // exact checkpoint
    weights.push(1 / (distSq * distSq)); // p = 4: anchors dominate locally
  }
  const total = weights.reduce((sum, w) => sum + w, 0);
  const blended = {} as Record<keyof PhysicsRow, number>;
  for (const key of PHYSICS_KEYS) {
    let acc = 0;
    EMOTION_ANCHORS.forEach((anchor, i) => {
      acc += ((weights[i] ?? 0) / total) * anchor.row[key];
    });
    blended[key] = acc;
  }
  return blended as PhysicsRow;
}

function mix(a: number, b: number, t: number): number {
  return a + (b - a) * t;
}

/**
 * The emotion engine's single entry point: affect triple → pool physics.
 * Continuous in all three inputs; exact at every table checkpoint.
 */
export function mapAffectToPoolPhysics(affect: Affect): PoolPhysics {
  const base = interpolateAnchors(affect.valence, affect.arousal);
  const burst = burstIntensity(affect);
  if (burst === 0) {
    return { ...base, dropletCount: Math.round(base.dropletCount) };
  }
  // A laugh burst pulls the whole field toward the Laughing anchor by its
  // intensity — droplets detach, ring pulses appear, tension drops.
  const blended = {} as Record<keyof PhysicsRow, number>;
  for (const key of PHYSICS_KEYS) blended[key] = mix(base[key], LAUGHING_ROW[key], burst);
  // Brief: laughter detaches 2–4 satellites; intensity scales 1 → 3 of them.
  blended.dropletCount = Math.round(1 + burst * 2);
  return blended as PoolPhysics;
}

/**
 * 600ms critically-damped smoother for the (v, a) point (brief §2: affect is
 * "smoothed with a 600ms critically-damped ease before hitting uniforms").
 * Burst is NOT smoothed — a laugh onset is an event, not a drift.
 */
export function createAffectSmoother(initial: Affect) {
  // Critically damped spring: x'' = −2ωx' − ω²(x−target). ω = 8 rad/s
  // settles (≤2% error) in ≈ 0.6s — the brief's 600ms ease.
  const OMEGA = 8;
  let v = initial.valence;
  let a = initial.arousal;
  let vVel = 0;
  let aVel = 0;
  return {
    /** Advance by dt seconds toward `target`; returns the smoothed affect. */
    step(target: Affect, dtSeconds: number): Affect {
      // Clamp dt: a background-tab resume must ease, not teleport-overshoot.
      const dt = Math.min(Math.max(dtSeconds, 0), 0.1);
      const stepAxis = (x: number, vel: number, goal: number): [number, number] => {
        const accel = -2 * OMEGA * vel - OMEGA * OMEGA * (x - goal);
        const newVel = vel + accel * dt;
        return [x + newVel * dt, newVel];
      };
      [v, vVel] = stepAxis(v, vVel, target.valence);
      [a, aVel] = stepAxis(a, aVel, target.arousal);
      return { valence: v, arousal: a, burst: target.burst };
    },
  };
}
