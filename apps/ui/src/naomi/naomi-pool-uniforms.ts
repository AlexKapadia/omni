/**
 * Uniform packing: (time, audio features, pool physics, flags) → the exact
 * float values uploaded to the pool shader each frame.
 *
 * This is the stateless-render seam (brief §1): the shader is a pure
 * function of its uniforms, and THIS function is a pure function of its
 * arguments — so (t, audio, affect) → pixels is deterministic end to end,
 * which the golden-frame tests enforce. No allocation surprises: callers
 * reuse one NaomiUniformValues via packNaomiUniforms(target,...) in the rAF
 * loop (zero-allocation budget, brief §5).
 */

import type { PoolPhysics } from "./naomi-affect-parameter-mapper";

/** Smoothed per-frame audio features (see naomi-audio-feature-extractor). */
export interface AudioFrameFeatures {
  /** RMS envelope after the emotion-driven attack/decay, 0..1. */
  readonly envelope: number;
  /** Band energies 0..1: low 0–300Hz, mid 300–2k, high 2k–8k. */
  readonly low: number;
  readonly mid: number;
  readonly high: number;
  /** Half-wave-rectified spectral flux (syllable pulses), 0..1. */
  readonly flux: number;
}

/** Silence — the features when no audio source is connected. */
export const SILENT_AUDIO_FEATURES: AudioFrameFeatures = {
  envelope: 0,
  low: 0,
  mid: 0,
  high: 0,
  flux: 0,
};

/** Mutable uniform slots, mirroring POOL_UNIFORM_NAMES' packing. */
export interface NaomiUniformValues {
  time: number;
  audio: Float32Array; // vec4: env, low, mid, high
  audioPulse: number;
  flow: Float32Array; // vec4: flowSpeed, rimFreq, interiorFreq, octaves
  shape: Float32Array; // vec4: rimAmpEffective, sminK, radiusBias, restOffset
  pulseA: Float32Array; // vec4: breatheDepth, bobDepth, bobHz, inwardBias
  pulseB: Float32Array; // vec4: ringDepth, ringHz, jitterAmp, jitterHz
  droplet: Float32Array; // vec2: count, burstSeed
  errorWeight: number;
}

export function createUniformValues(): NaomiUniformValues {
  return {
    time: 0,
    audio: new Float32Array(4),
    audioPulse: 0,
    flow: new Float32Array(4),
    shape: new Float32Array(4),
    pulseA: new Float32Array(4),
    pulseB: new Float32Array(4),
    droplet: new Float32Array(2),
    errorWeight: 0,
  };
}

export interface UniformPackingFlags {
  /** Reduced motion: freeze time and force the resting envelope (brief §6). */
  readonly reducedMotion: boolean;
  /** Error / fail-closed system state — 2px rim, stilled pool. */
  readonly errorState: boolean;
  /** Deterministic seed for droplet orbits (changes per laugh burst). */
  readonly burstSeed: number;
}

/**
 * Pack one frame's uniforms. Pure and deterministic: identical arguments
 * produce bitwise-identical Float32 slots (asserted by the determinism test).
 */
export function packNaomiUniforms(
  target: NaomiUniformValues,
  timeSeconds: number,
  audio: AudioFrameFeatures,
  physics: PoolPhysics,
  flags: UniformPackingFlags,
): NaomiUniformValues {
  // Reduced motion: the pool is a STILL frame — freeze t at 0 and silence
  // the audio drive so the drawn state is exactly the state's rest pose.
  const frozen = flags.reducedMotion;
  target.time = frozen ? 0 : timeSeconds;
  const features = frozen ? SILENT_AUDIO_FEATURES : audio;
  target.audio[0] = features.envelope;
  target.audio[1] = features.low;
  target.audio[2] = features.mid;
  target.audio[3] = features.high;
  target.audioPulse = features.flux;
  target.flow[0] = physics.flowSpeed;
  target.flow[1] = physics.rimNoiseFrequency;
  target.flow[2] = physics.interiorNoiseFrequency;
  target.flow[3] = physics.octaves;
  // Rim amplitude couples to the live envelope exactly as the emotion table
  // specifies ("0.05 × ttsEnv"): coupling 1 → fully envelope-driven.
  const rimAmpEffective =
    physics.rimAmplitude * (1 - physics.audioCoupling + physics.audioCoupling * features.envelope);
  target.shape[0] = rimAmpEffective;
  target.shape[1] = physics.surfaceTension;
  target.shape[2] = physics.radiusBias;
  target.shape[3] = physics.restOffset;
  target.pulseA[0] = physics.breatheDepth;
  target.pulseA[1] = physics.bobDepth;
  target.pulseA[2] = physics.bobFrequencyHz;
  target.pulseA[3] = physics.inwardDriftBias;
  target.pulseB[0] = physics.ringPulseDepth;
  target.pulseB[1] = physics.ringPulseFrequencyHz;
  target.pulseB[2] = physics.jitterAmplitude;
  target.pulseB[3] = physics.jitterFrequencyHz;
  target.droplet[0] = physics.dropletCount;
  target.droplet[1] = flags.burstSeed;
  target.errorWeight = flags.errorState ? 1 : 0;
  return target;
}
