/**
 * Performance governor: the 120-frame p95 window, the 2s sustain before a
 * downgrade, the full degradation ladder order (renderScale → octaves →
 * fps cap), and the 30s hysteretic recovery — boundary-exact.
 */
import { describe, expect, it } from "vitest";
import { NaomiPerformanceGovernor } from "./naomi-performance-governor";

/** Feed `count` frames of `deltaMs` starting at `startMs`; returns end time. */
function feed(
  governor: NaomiPerformanceGovernor,
  deltaMs: number,
  count: number,
  startMs: number,
): number {
  let now = startMs;
  for (let i = 0; i < count; i++) {
    now += deltaMs;
    governor.recordFrame(deltaMs, now);
  }
  return now;
}

describe("baseline", () => {
  it("starts at full quality", () => {
    const g = new NaomiPerformanceGovernor();
    expect(g.quality).toEqual({ renderScale: 1.0, octaveCap: 5, fpsCap: 60 });
  });

  it("no p95 until the 120-frame window fills — no premature judgement", () => {
    const g = new NaomiPerformanceGovernor();
    feed(g, 40, 119, 0); // heavy frames, but window not full
    expect(g.p95Ms).toBeNull();
    expect(g.quality.renderScale).toBe(1.0);
  });

  it("steady 60fps never downgrades", () => {
    const g = new NaomiPerformanceGovernor();
    feed(g, 16.7, 1000, 0);
    expect(g.quality.renderScale).toBe(1.0);
  });

  it("p95 boundary: exactly 17ms is WITHIN budget (strictly-over triggers)", () => {
    const g = new NaomiPerformanceGovernor();
    feed(g, 17, 500, 0); // p95 == 17 → not > 17
    expect(g.quality.renderScale).toBe(1.0);
  });
});

// At 40ms frames one downgrade takes EXACTLY 170 frames: 120 to fill the
// window, then 50 more (2000ms / 40ms) of sustained over-budget p95.
const FRAMES_PER_DOWNGRADE_AT_40MS = 170;

describe("downgrade ladder", () => {
  it("sustained heavy frames walk the ladder in the brief's order", () => {
    const g = new NaomiPerformanceGovernor();
    let now = 0;
    const expectedLadder = [
      { renderScale: 0.75, octaveCap: 5, fpsCap: 60 },
      { renderScale: 0.5, octaveCap: 5, fpsCap: 60 },
      { renderScale: 0.5, octaveCap: 3, fpsCap: 60 },
      { renderScale: 0.5, octaveCap: 3, fpsCap: 30 },
    ];
    for (const expected of expectedLadder) {
      now = feed(g, 40, FRAMES_PER_DOWNGRADE_AT_40MS, now);
      expect(g.quality).toEqual(expected);
    }
    // Bottom of the ladder: further pressure changes nothing (no crash).
    now = feed(g, 40, 500, now);
    expect(g.quality).toEqual(expectedLadder[3]);
  });

  it("one frame short of the 2s sustain does NOT downgrade (boundary-exact)", () => {
    const g = new NaomiPerformanceGovernor();
    feed(g, 40, FRAMES_PER_DOWNGRADE_AT_40MS - 1, 0);
    expect(g.quality.renderScale).toBe(1.0);
    // ...and the very next heavy frame tips it over.
    feed(g, 40, 1, (FRAMES_PER_DOWNGRADE_AT_40MS - 1) * 40);
    expect(g.quality.renderScale).toBe(0.75);
  });

  it("a SHORT spike (<2s over budget incl. washout) never downgrades", () => {
    const g = new NaomiPerformanceGovernor();
    let now = feed(g, 16, 200, 0); // healthy full window
    // 12 bad frames (0.48s) + the ~1.1s the spike takes to wash out of the
    // rolling window stays under the 2s sustain bar.
    now = feed(g, 40, 12, now);
    feed(g, 10, 300, now);
    expect(g.quality.renderScale).toBe(1.0);
  });

  it("downgrade resets the window: the new level is measured fresh", () => {
    const g = new NaomiPerformanceGovernor();
    const now = feed(g, 40, FRAMES_PER_DOWNGRADE_AT_40MS, 0);
    expect(g.quality.renderScale).toBe(0.75);
    expect(g.p95Ms).toBeNull(); // window cleared — old lag can't double-punish
    feed(g, 12, 500, now); // new level performs: no further downgrade
    expect(g.quality.renderScale).toBe(0.75);
  });
});

describe("hysteretic recovery", () => {
  it("recovers ONE level after 30s continuously under budget", () => {
    const g = new NaomiPerformanceGovernor();
    let now = feed(g, 40, FRAMES_PER_DOWNGRADE_AT_40MS, 0); // → 0.75
    expect(g.quality.renderScale).toBe(0.75);
    // Window refills for 1.2s before the stability clock starts, so 32.5s
    // of light frames comfortably crosses the 30s bar.
    now = feed(g, 10, 3250, now);
    expect(g.quality.renderScale).toBe(1.0);
  });

  it("29s of stability is NOT enough (hysteresis boundary)", () => {
    const g = new NaomiPerformanceGovernor();
    let now = feed(g, 40, FRAMES_PER_DOWNGRADE_AT_40MS, 0);
    expect(g.quality.renderScale).toBe(0.75);
    now = feed(g, 10, 2890, now); // 28.9s under budget (minus 1.2s refill)
    expect(g.quality.renderScale).toBe(0.75);
  });

  it("a spike during recovery resets the stability clock", () => {
    const g = new NaomiPerformanceGovernor();
    let now = feed(g, 40, FRAMES_PER_DOWNGRADE_AT_40MS, 0); // → 0.75
    now = feed(g, 10, 2000, now); // 20s stable
    // A 0.8s spike: over budget long enough to reset stability, but its
    // over-budget span (spike + 1.14s window washout ≈ 1.7s) stays under
    // the 2s sustain bar, so it does NOT downgrade further.
    now = feed(g, 40, 20, now);
    now = feed(g, 10, 1500, now); // only ~15s stable since the spike
    expect(g.quality.renderScale).toBe(0.75); // clock restarted — still down
  });

  it("never recovers past full quality", () => {
    const g = new NaomiPerformanceGovernor();
    feed(g, 10, 10000, 0); // minutes of perfection at level 0
    expect(g.quality.renderScale).toBe(1.0);
  });
});
