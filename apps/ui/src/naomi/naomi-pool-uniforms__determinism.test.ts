/**
 * Stateless-render contract (brief §1/§5): the uniform packing is a PURE
 * function — identical (t, audio, affect) inputs must produce bitwise-
 * identical uniform slots across arbitrarily many invocations, and reduced
 * motion must freeze time and silence the drive. This is the CPU half of
 * the golden-frame determinism guarantee (the GPU half is Playwright's
 * readPixels hash, per the measurement plan).
 */
import { describe, expect, it } from "vitest";
import { mapAffectToPoolPhysics } from "./naomi-affect-parameter-mapper";
import { clampAffect } from "./naomi-affect-types";
import {
  createUniformValues,
  packNaomiUniforms,
  SILENT_AUDIO_FEATURES,
  type AudioFrameFeatures,
} from "./naomi-pool-uniforms";

const AUDIO: AudioFrameFeatures = { envelope: 0.42, low: 0.3, mid: 0.55, high: 0.18, flux: 0.7 };
const FLAGS = { reducedMotion: false, errorState: false, burstSeed: 0.618 };

function packOnce(time: number, audio: AudioFrameFeatures, v: number, a: number) {
  const physics = mapAffectToPoolPhysics(clampAffect(v, a, null));
  const target = createUniformValues();
  packNaomiUniforms(target, time, audio, physics, FLAGS);
  return target;
}

describe("determinism — same inputs, identical uniforms", () => {
  it("100 repetitions produce bitwise-identical Float32 slots", () => {
    const reference = packOnce(12.345, AUDIO, 0.33, 0.61);
    for (let i = 0; i < 100; i++) {
      const again = packOnce(12.345, AUDIO, 0.33, 0.61);
      expect(again.time).toBe(reference.time);
      expect(again.audioPulse).toBe(reference.audioPulse);
      expect(again.errorWeight).toBe(reference.errorWeight);
      for (const key of ["audio", "flow", "shape", "pulseA", "pulseB", "droplet"] as const) {
        // Bitwise comparison via the underlying bytes — NaN-safe and exact.
        expect(new Uint8Array(again[key].buffer)).toEqual(new Uint8Array(reference[key].buffer));
      }
    }
  });

  it("a reused target produces the same values as a fresh one (no state bleed)", () => {
    const reused = createUniformValues();
    packNaomiUniforms(reused, 99, AUDIO, mapAffectToPoolPhysics(clampAffect(-0.8, 0.9, null)), FLAGS);
    packNaomiUniforms(reused, 12.345, AUDIO, mapAffectToPoolPhysics(clampAffect(0.33, 0.61, null)), FLAGS);
    const fresh = packOnce(12.345, AUDIO, 0.33, 0.61);
    expect(Array.from(reused.flow)).toEqual(Array.from(fresh.flow));
    expect(Array.from(reused.shape)).toEqual(Array.from(fresh.shape));
    expect(reused.time).toBe(fresh.time);
  });
});

describe("audio coupling arithmetic — exact to the unit", () => {
  it("speaking rim amplitude is 0.05 × envelope, exactly (table cell)", () => {
    const physics = mapAffectToPoolPhysics(clampAffect(0.1, 0.5, null)); // speaking
    const target = createUniformValues();
    packNaomiUniforms(target, 0, { ...AUDIO, envelope: 0.5 }, physics, FLAGS);
    expect(target.shape[0]).toBeCloseTo(0.05 * 0.5, 7); // rimAmp × ttsEnv
  });

  it("idle rim amplitude ignores the envelope entirely (coupling 0)", () => {
    const physics = mapAffectToPoolPhysics(clampAffect(0, 0.1, null));
    const loud = createUniformValues();
    const silent = createUniformValues();
    packNaomiUniforms(loud, 0, { ...AUDIO, envelope: 1 }, physics, FLAGS);
    packNaomiUniforms(silent, 0, { ...AUDIO, envelope: 0 }, physics, FLAGS);
    expect(loud.shape[0]).toBe(silent.shape[0]);
    expect(loud.shape[0]).toBeCloseTo(0.015, 7); // the idle table cell
  });
});

describe("reduced motion (brief §6) — a still pool", () => {
  it("freezes time at 0 and forces the silent envelope", () => {
    const physics = mapAffectToPoolPhysics(clampAffect(0.7, 0.6, null));
    const target = createUniformValues();
    packNaomiUniforms(target, 123.456, AUDIO, physics, { ...FLAGS, reducedMotion: true });
    expect(target.time).toBe(0);
    expect(Array.from(target.audio)).toEqual([0, 0, 0, 0]);
    expect(target.audioPulse).toBe(SILENT_AUDIO_FEATURES.flux);
  });

  it("still carries the state's rest-pose physics (state stays legible)", () => {
    const physics = mapAffectToPoolPhysics(clampAffect(0.7, 0.6, null)); // happy
    const target = createUniformValues();
    packNaomiUniforms(target, 50, AUDIO, physics, { ...FLAGS, reducedMotion: true });
    expect(target.shape[2]).toBeCloseTo(1.06, 6); // happy radius bias survives
  });
});

describe("error state flag", () => {
  it("errorWeight is exactly 0 or 1 — the shader's 2px rim switch", () => {
    const physics = mapAffectToPoolPhysics(clampAffect(0, 0.2, null));
    const target = createUniformValues();
    packNaomiUniforms(target, 1, AUDIO, physics, { ...FLAGS, errorState: true });
    expect(target.errorWeight).toBe(1);
    packNaomiUniforms(target, 1, AUDIO, physics, { ...FLAGS, errorState: false });
    expect(target.errorWeight).toBe(0);
  });
});
