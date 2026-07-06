/**
 * Emotion engine exactness: the brief's emotion→physics table rows are the
 * canonical checkpoints the CONTINUOUS field must reproduce — to the unit,
 * every specified cell (brief §2: "the table rows are the canonical
 * checkpoints these formulas must reproduce (test fixture)").
 * Plus continuity, boundary, and burst behaviour between the checkpoints.
 */
import { describe, expect, it } from "vitest";
import {
  createAffectSmoother,
  EMOTION_ANCHORS,
  ERROR_STATE_PHYSICS,
  mapAffectToPoolPhysics,
  type PoolPhysics,
} from "./naomi-affect-parameter-mapper";
import { clampAffect, IDLE_AFFECT } from "./naomi-affect-types";

const at = (v: number, a: number, laugh = 0): PoolPhysics =>
  mapAffectToPoolPhysics(
    clampAffect(v, a, laugh > 0 ? { kind: "laugh", intensity: laugh } : null),
  );

// Every SPECIFIED cell of the brief's table, verbatim. Columns:
// [v, a, flowSpeed, rimFreq, intFreq, octaves, rimAmp, k, attack, decay, radiusBias]
const TABLE: ReadonlyArray<[string, number, number, number, number, number, number, number, number, number, number, number]> = [
  ["idle",      0,    0.1,  0.04, 1.2, 1.6, 3, 0.015, 0.30, 0.25, 0.97, 1.00],
  ["listening", 0,    0.35, 0.12, 1.4, 1.8, 3, 0.03,  0.28, 0.5,  0.93, 1.02],
  ["thinking",  0.1,  0.45, 0.18, 1.0, 2.2, 4, 0.02,  0.26, 0.3,  0.96, 0.98],
  ["speaking",  0.1,  0.5,  0.25, 1.5, 2.0, 4, 0.05,  0.25, 0.5,  0.93, 1.02],
  ["happy",     0.7,  0.6,  0.32, 1.0, 1.6, 3, 0.06,  0.34, 0.5,  0.94, 1.06],
  ["laughing",  0.8,  0.85, 0.38, 1.3, 1.8, 4, 0.08,  0.20, 0.7,  0.90, 1.04],
  ["agitated",  -0.6, 0.9,  0.50, 2.8, 3.2, 5, 0.07,  0.06, 0.8,  0.85, 0.97],
  ["sad",       -0.5, 0.15, 0.06, 0.9, 1.4, 3, 0.012, 0.32, 0.2,  0.98, 0.96],
];

describe("table checkpoints reproduce EXACTLY from the continuous field", () => {
  it.each(TABLE)(
    "%s (v=%f, a=%f)",
    (_name, v, a, flow, rimF, intF, oct, rimAmp, k, attack, decay, radiusBias) => {
      const p = at(v, a);
      expect(p.flowSpeed).toBe(flow);
      expect(p.rimNoiseFrequency).toBe(rimF);
      expect(p.interiorNoiseFrequency).toBe(intF);
      expect(p.octaves).toBe(oct);
      expect(p.rimAmplitude).toBe(rimAmp);
      expect(p.surfaceTension).toBe(k);
      expect(p.envelopeAttack).toBe(attack);
      expect(p.envelopeDecay).toBe(decay);
      expect(p.radiusBias).toBe(radiusBias);
    },
  );

  it("reproduces the state-specific pulse cells verbatim", () => {
    expect(at(0.7, 0.6).bobFrequencyHz).toBe(0.3); // happy: bob 0.3Hz
    expect(at(0.7, 0.6).bobDepth).toBe(0.02); // depth 2%
    expect(at(0.8, 0.85).ringPulseDepth).toBe(0.08); // laughing: depth 8%
    expect(at(0.8, 0.85).ringPulseFrequencyHz).toBe(5); // syllable rate 4–6Hz
    expect(at(-0.6, 0.9).jitterFrequencyHz).toBe(10); // agitated: 8–12Hz
    expect(at(-0.5, 0.15).restOffset).toBe(-0.02); // sad: sits 2% lower
    expect(at(0.1, 0.45).inwardDriftBias).toBe(0.05); // thinking: inward +0.05
  });

  it("audio coupling: listening/speaking/happy rims ride the envelope; idle/agitated do not", () => {
    expect(at(0, 0.35).audioCoupling).toBe(1);
    expect(at(0.1, 0.5).audioCoupling).toBe(1);
    expect(at(0.7, 0.6).audioCoupling).toBe(1);
    expect(at(0, 0.1).audioCoupling).toBe(0);
    expect(at(-0.6, 0.9).audioCoupling).toBe(0);
  });

  it("error state is the table's fail-closed row, as a discrete override", () => {
    expect(ERROR_STATE_PHYSICS.flowSpeed).toBe(0.05);
    expect(ERROR_STATE_PHYSICS.rimAmplitude).toBe(0.01);
    expect(ERROR_STATE_PHYSICS.radiusBias).toBe(0.95);
    expect(ERROR_STATE_PHYSICS.surfaceTension).toBe(0.30);
  });
});

describe("continuity — the field never switches discretely", () => {
  it("a tiny affect step never jumps any parameter (Lipschitz-style bound)", () => {
    // Walk a fine grid; adjacent samples must differ by a small amount.
    const step = 0.01;
    for (let v = -1; v <= 1 - step; v += 0.25) {
      for (let a = 0; a <= 1 - step; a += 0.125) {
        const here = at(v, a);
        const there = at(v + step, a + step);
        expect(Math.abs(there.flowSpeed - here.flowSpeed)).toBeLessThan(0.1);
        expect(Math.abs(there.surfaceTension - here.surfaceTension)).toBeLessThan(0.1);
        expect(Math.abs(there.radiusBias - here.radiusBias)).toBeLessThan(0.05);
      }
    }
  });

  it("just off a checkpoint stays close to the checkpoint (no cliff)", () => {
    const happy = at(0.7, 0.6);
    const nearHappy = at(0.7 + 1e-4, 0.6 - 1e-4);
    expect(Math.abs(nearHappy.flowSpeed - happy.flowSpeed)).toBeLessThan(0.01);
    expect(Math.abs(nearHappy.surfaceTension - happy.surfaceTension)).toBeLessThan(0.01);
  });

  it("interpolated points stay within the anchor value envelope", () => {
    for (let v = -1; v <= 1; v += 0.2) {
      for (let a = 0; a <= 1; a += 0.1) {
        const p = at(v, a);
        expect(p.flowSpeed).toBeGreaterThanOrEqual(0.04);
        expect(p.flowSpeed).toBeLessThanOrEqual(0.5);
        expect(p.surfaceTension).toBeGreaterThanOrEqual(0.06);
        expect(p.surfaceTension).toBeLessThanOrEqual(0.34);
        expect(p.octaves).toBeGreaterThanOrEqual(3);
        expect(p.octaves).toBeLessThanOrEqual(5);
      }
    }
  });
});

describe("burst (laugh) behaviour", () => {
  it("no burst → no droplets anywhere on the field", () => {
    expect(at(0, 0.1).dropletCount).toBe(0);
    expect(at(0.5, 0.5).dropletCount).toBe(0);
  });

  it("full burst detaches 3 satellites; intensity scales 1→3", () => {
    expect(at(0, 0.5, 1).dropletCount).toBe(3);
    expect(at(0, 0.5, 0.5).dropletCount).toBe(2);
    expect(at(0, 0.5, 0.05).dropletCount).toBe(1);
  });

  it("full burst from idle lands exactly on the Laughing row physics", () => {
    const burst = at(0, 0.1, 1);
    const anchor = EMOTION_ANCHORS.find((a) => a.name === "laughing");
    expect(anchor).toBeDefined();
    const laughing = anchor!.row;
    expect(burst.flowSpeed).toBeCloseTo(laughing.flowSpeed, 10);
    expect(burst.surfaceTension).toBeCloseTo(laughing.surfaceTension, 10);
    expect(burst.ringPulseDepth).toBeCloseTo(laughing.ringPulseDepth, 10);
  });

  it("burst blend is monotone in intensity for surface tension (tension drops)", () => {
    const idleK = at(0, 0.1, 0).surfaceTension;
    const halfK = at(0, 0.1, 0.5).surfaceTension;
    const fullK = at(0, 0.1, 1).surfaceTension;
    expect(halfK).toBeLessThan(idleK);
    expect(fullK).toBeLessThan(halfK);
  });
});

describe("input hardening — hostile affect can never corrupt the physics", () => {
  it.each([
    [Number.NaN, Number.NaN],
    [Infinity, -Infinity],
    [1e9, -1e9],
    [-1.0001, 1.0001],
  ])("v=%p a=%p clamps to finite physics", (v, a) => {
    const p = at(v as number, a as number);
    for (const value of Object.values(p)) {
      expect(Number.isFinite(value)).toBe(true);
    }
  });
});

describe("600ms critically-damped smoother", () => {
  it("settles onto the target within ~600ms and never rings past it (critical damping)", () => {
    const smoother = createAffectSmoother(IDLE_AFFECT);
    const target = clampAffect(0.7, 0.6, null);
    let latest = IDLE_AFFECT;
    let maxValence = -Infinity;
    for (let i = 0; i < 90; i++) {
      latest = smoother.step(target, 1 / 120); // 750ms at 120Hz
      maxValence = Math.max(maxValence, latest.valence);
    }
    expect(Math.abs(latest.valence - 0.7)).toBeLessThan(0.02); // settled
    expect(Math.abs(latest.arousal - 0.6)).toBeLessThan(0.02);
    // Critical damping: no meaningful overshoot (tiny numerical slack only).
    expect(maxValence).toBeLessThanOrEqual(0.7 + 0.005);
  });

  it("clamps a huge dt (background-tab resume) instead of exploding", () => {
    const smoother = createAffectSmoother(IDLE_AFFECT);
    const stepped = smoother.step(clampAffect(1, 1, null), 60); // a minute of gap
    expect(Number.isFinite(stepped.valence)).toBe(true);
    expect(Math.abs(stepped.valence)).toBeLessThanOrEqual(1.5);
  });
});
