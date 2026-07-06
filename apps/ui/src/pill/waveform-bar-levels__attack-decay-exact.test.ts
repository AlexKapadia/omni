/**
 * Waveform math to the unit — the design numbers are a contract:
 * bar 2.5px, gap (w − bars·2.5)/(bars−1), attack 0.5, decay 0.93, floor
 * 2px, idle level 0.06, pill geometry 110×18×20. Zero numerical drift.
 */
import { describe, expect, it } from "vitest";

import {
  ATTACK,
  BAR_WIDTH_PX,
  DECAY,
  IDLE_FLOOR_LEVEL,
  MIN_BAR_HEIGHT_PX,
  PILL_WAVEFORM,
  barGapPx,
  barHeightPx,
  barTargetsFromTimeDomain,
  barXPx,
  stepBarLevel,
} from "./waveform-bar-levels";

describe("design constants are pinned", () => {
  it("matches design §8 / §07 exactly", () => {
    expect(BAR_WIDTH_PX).toBe(2.5);
    expect(ATTACK).toBe(0.5);
    expect(DECAY).toBe(0.93);
    expect(MIN_BAR_HEIGHT_PX).toBe(2);
    expect(IDLE_FLOOR_LEVEL).toBe(0.06);
    expect(PILL_WAVEFORM).toEqual({ width: 110, height: 18, bars: 20 });
  });
});

describe("bar layout — even gaps, exact", () => {
  it("pill gap = (110 − 20·2.5)/19", () => {
    expect(barGapPx(110, 20)).toBeCloseTo((110 - 20 * 2.5) / 19, 12);
  });

  it("first bar at x=0; last bar's right edge lands exactly at the width", () => {
    expect(barXPx(0, 110, 20)).toBe(0);
    expect(barXPx(19, 110, 20) + BAR_WIDTH_PX).toBeCloseTo(110, 9);
  });

  it("degenerate single-bar layout has no gap", () => {
    expect(barGapPx(110, 1)).toBe(0);
    expect(barXPx(0, 110, 1)).toBe(0);
  });
});

describe("attack / decay stepping — exact arithmetic", () => {
  it("attack: lv += (target − lv) · 0.5", () => {
    expect(stepBarLevel(0.2, 1.0)).toBeCloseTo(0.2 + (1.0 - 0.2) * 0.5, 12);
    expect(stepBarLevel(0.0, 0.5)).toBeCloseTo(0.25, 12);
  });

  it("decay: lv · 0.93, but never below the target (sustain holds)", () => {
    expect(stepBarLevel(0.8, 0.06)).toBeCloseTo(0.8 * 0.93, 12);
    expect(stepBarLevel(0.5, 0.5)).toBe(0.5); // equal: hold, don't sag
    expect(stepBarLevel(0.061, 0.06)).toBeCloseTo(0.06, 12); // clamps at target
  });

  it("a silent tail decays geometrically toward the floor", () => {
    let level = 1.0;
    for (let i = 0; i < 10; i += 1) level = stepBarLevel(level, IDLE_FLOOR_LEVEL);
    expect(level).toBeCloseTo(Math.max(IDLE_FLOOR_LEVEL, 1.0 * 0.93 ** 10), 12);
  });
});

describe("bar height — floored at 2px", () => {
  it("idle floor level renders the 2px minimum in an 18px canvas", () => {
    // 0.06 · 18 = 1.08 < 2 → the floor wins.
    expect(barHeightPx(IDLE_FLOOR_LEVEL, 18)).toBe(2);
  });

  it("boundary: exactly 2px passes through; just under floors", () => {
    expect(barHeightPx(2 / 18, 18)).toBe(2);
    expect(barHeightPx(2 / 18 - 1e-9, 18)).toBe(2);
    expect(barHeightPx(0.5, 18)).toBe(9);
    expect(barHeightPx(1, 18)).toBe(18);
  });
});

describe("time-domain bucketing — real levels in, per-bar targets out", () => {
  it("silence (all 128) yields the idle floor on every bar", () => {
    const samples = new Uint8Array(128).fill(128);
    expect(barTargetsFromTimeDomain(samples, 20)).toEqual(
      new Array<number>(20).fill(IDLE_FLOOR_LEVEL),
    );
  });

  it("full-scale audio clamps to 1", () => {
    const samples = new Uint8Array(128).fill(255);
    for (const target of barTargetsFromTimeDomain(samples, 20)) {
      expect(target).toBe(1);
    }
  });

  it("a loud bucket only raises ITS bar", () => {
    const samples = new Uint8Array(120).fill(128);
    // Bucket size 6 for 20 bars; make bar 3's bucket (samples 18..23) loud.
    for (let i = 18; i < 24; i += 1) samples[i] = 255;
    const targets = barTargetsFromTimeDomain(samples, 20);
    expect(targets[3]).toBeGreaterThan(IDLE_FLOOR_LEVEL);
    expect(targets[2]).toBe(IDLE_FLOOR_LEVEL);
    expect(targets[4]).toBe(IDLE_FLOOR_LEVEL);
  });

  it("empty input degrades to the idle floor (never NaN)", () => {
    expect(barTargetsFromTimeDomain(new Uint8Array(0), 20)).toEqual(
      new Array<number>(20).fill(IDLE_FLOOR_LEVEL),
    );
  });
});
