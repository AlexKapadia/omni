/**
 * Audio feature computation: envelope attack/decay arithmetic exact to the
 * unit (the house waveform physics), band split boundaries at 300Hz / 2kHz /
 * 8kHz, and spectral flux half-wave rectification (rises pulse, falls don't).
 */
import { describe, expect, it } from "vitest";
import {
  computeAudioFrameFeatures,
  createAudioFeatureState,
} from "./naomi-audio-feature-extractor";

const SAMPLE_RATE = 24000;
const BINS = 512; // fftSize 1024 → 512 bins, binHz = 12000/512 = 23.4375

function silentTime(): Float32Array {
  return new Float32Array(1024);
}
function constantTime(value: number): Float32Array {
  return new Float32Array(1024).fill(value);
}
function silentSpectrum(): Uint8Array {
  return new Uint8Array(BINS);
}

describe("envelope attack/decay — exact arithmetic", () => {
  it("attack: env += (target − env) × attack, exactly", () => {
    const state = createAudioFeatureState(BINS);
    // |x| = 0.4 constant → rms 0.4 → target = min(1, 0.4×2.5) = 1.
    const features = computeAudioFrameFeatures(
      constantTime(0.4), silentSpectrum(), SAMPLE_RATE, 0.5, 0.93, state,
    );
    expect(features.envelope).toBeCloseTo(0.5, 12); // 0 + (1−0)×0.5
    const second = computeAudioFrameFeatures(
      constantTime(0.4), silentSpectrum(), SAMPLE_RATE, 0.5, 0.93, state,
    );
    expect(second.envelope).toBeCloseTo(0.75, 12); // 0.5 + (1−0.5)×0.5
  });

  it("decay: env ×= decay when the target falls, exactly", () => {
    const state = createAudioFeatureState(BINS);
    computeAudioFrameFeatures(constantTime(0.4), silentSpectrum(), SAMPLE_RATE, 1, 0.93, state);
    expect(state.envelope).toBeCloseTo(1, 12); // full attack in one frame
    const decayed = computeAudioFrameFeatures(
      silentTime(), silentSpectrum(), SAMPLE_RATE, 1, 0.93, state,
    );
    expect(decayed.envelope).toBeCloseTo(0.93, 12);
    const decayedTwice = computeAudioFrameFeatures(
      silentTime(), silentSpectrum(), SAMPLE_RATE, 1, 0.93, state,
    );
    expect(decayedTwice.envelope).toBeCloseTo(0.93 * 0.93, 12);
  });

  it("silence in, zero out — and an empty buffer never divides by zero", () => {
    const state = createAudioFeatureState(BINS);
    const features = computeAudioFrameFeatures(
      new Float32Array(0), new Uint8Array(0), SAMPLE_RATE, 0.5, 0.93, state,
    );
    expect(features.envelope).toBe(0);
    expect(features.flux).toBe(0);
    expect(Number.isNaN(features.low)).toBe(false);
  });
});

describe("band energies — boundary-exact bin mapping", () => {
  const binHz = SAMPLE_RATE / 2 / BINS; // 23.4375 Hz per bin

  it("energy at 100Hz lands ONLY in the low band", () => {
    const spectrum = silentSpectrum();
    spectrum[Math.round(100 / binHz)] = 255;
    const state = createAudioFeatureState(BINS);
    const f = computeAudioFrameFeatures(silentTime(), spectrum, SAMPLE_RATE, 0.5, 0.93, state);
    expect(f.low).toBeGreaterThan(0);
    expect(f.mid).toBe(0);
    expect(f.high).toBe(0);
  });

  it("energy at 1kHz lands ONLY in the mid band", () => {
    const spectrum = silentSpectrum();
    spectrum[Math.round(1000 / binHz)] = 255;
    const state = createAudioFeatureState(BINS);
    const f = computeAudioFrameFeatures(silentTime(), spectrum, SAMPLE_RATE, 0.5, 0.93, state);
    expect(f.low).toBe(0);
    expect(f.mid).toBeGreaterThan(0);
    expect(f.high).toBe(0);
  });

  it("energy at 5kHz lands ONLY in the high band", () => {
    const spectrum = silentSpectrum();
    spectrum[Math.round(5000 / binHz)] = 255;
    const state = createAudioFeatureState(BINS);
    const f = computeAudioFrameFeatures(silentTime(), spectrum, SAMPLE_RATE, 0.5, 0.93, state);
    expect(f.low).toBe(0);
    expect(f.mid).toBe(0);
    expect(f.high).toBeGreaterThan(0);
  });

  it("a full-scale flat spectrum normalises each band to exactly 1", () => {
    const spectrum = new Uint8Array(BINS).fill(255);
    const state = createAudioFeatureState(BINS);
    const f = computeAudioFrameFeatures(silentTime(), spectrum, SAMPLE_RATE, 0.5, 0.93, state);
    expect(f.low).toBe(1);
    expect(f.mid).toBe(1);
    expect(f.high).toBe(1);
  });
});

describe("spectral flux — half-wave rectified (onsets pulse, decays do not)", () => {
  it("a sudden onset produces flux; the SAME steady frame after produces none", () => {
    const state = createAudioFeatureState(BINS);
    const loud = new Uint8Array(BINS).fill(200);
    const onset = computeAudioFrameFeatures(silentTime(), loud, SAMPLE_RATE, 0.5, 0.93, state);
    expect(onset.flux).toBeGreaterThan(0);
    const steady = computeAudioFrameFeatures(silentTime(), loud, SAMPLE_RATE, 0.5, 0.93, state);
    expect(steady.flux).toBe(0);
  });

  it("a fall-off produces ZERO flux (half-wave rectification)", () => {
    const state = createAudioFeatureState(BINS);
    computeAudioFrameFeatures(silentTime(), new Uint8Array(BINS).fill(200), SAMPLE_RATE, 0.5, 0.93, state);
    const falling = computeAudioFrameFeatures(
      silentTime(), silentSpectrum(), SAMPLE_RATE, 0.5, 0.93, state,
    );
    expect(falling.flux).toBe(0);
  });

  it("flux saturates at 1 for a maximal onset", () => {
    const state = createAudioFeatureState(BINS);
    const f = computeAudioFrameFeatures(
      silentTime(), new Uint8Array(BINS).fill(255), SAMPLE_RATE, 0.5, 0.93, state,
    );
    expect(f.flux).toBe(1);
  });
});
