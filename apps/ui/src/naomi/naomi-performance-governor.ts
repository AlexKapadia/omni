/**
 * 60fps performance governor (brief §5): a pure state machine fed rAF frame
 * deltas that degrades render quality stepwise when the rolling 120-frame
 * p95 exceeds 17ms for 2 seconds, and recovers hysteretically after 30s of
 * stable frames.
 *
 * Degradation ladder: renderScale 1.0 → 0.75 → 0.5 → octave cap 3 →
 * 30fps cap with time-dilation. Pure logic (no DOM, no clock reads of its
 * own) so every transition is exactly unit-testable.
 */

const WINDOW_FRAMES = 120;
const P95_BUDGET_MS = 17;
const SUSTAIN_BEFORE_DOWNGRADE_MS = 2000;
const STABLE_BEFORE_RECOVER_MS = 30000;

/** The quality levels, best → worst. */
export interface GovernorQuality {
  readonly renderScale: number;
  /** Octave ceiling applied on top of the emotion engine's octaves. */
  readonly octaveCap: number;
  /** Frame cadence cap in fps (30 = half-rate with time dilation). */
  readonly fpsCap: number;
}

const QUALITY_LADDER: readonly GovernorQuality[] = [
  { renderScale: 1.0, octaveCap: 5, fpsCap: 60 },
  { renderScale: 0.75, octaveCap: 5, fpsCap: 60 },
  { renderScale: 0.5, octaveCap: 5, fpsCap: 60 },
  { renderScale: 0.5, octaveCap: 3, fpsCap: 60 },
  { renderScale: 0.5, octaveCap: 3, fpsCap: 30 },
];

export class NaomiPerformanceGovernor {
  private deltas: number[] = [];
  private level = 0;
  private overBudgetSinceMs: number | null = null;
  private stableSinceMs: number | null = null;

  /** Current quality settings for the renderer. */
  get quality(): GovernorQuality {
    // The level is clamped by construction; index 0 is the safe fallback.
    return QUALITY_LADDER[this.level] ?? QUALITY_LADDER[0]!;
  }

  /** Ladder position 0 (best) .. 4 (worst) — for the dev readout. */
  get level_(): number {
    return this.level;
  }

  /** Rolling p95 of the recorded deltas, ms (null until the window fills). */
  get p95Ms(): number | null {
    if (this.deltas.length < WINDOW_FRAMES) return null;
    const sorted = [...this.deltas].sort((a, b) => a - b);
    const value = sorted[Math.min(sorted.length - 1, Math.ceil(0.95 * sorted.length) - 1)];
    return value === undefined ? null : value;
  }

  /**
   * Record one frame. `nowMs` is the caller's clock (injectable for tests).
   * Returns true when the quality level CHANGED (renderer must resize).
   */
  recordFrame(deltaMs: number, nowMs: number): boolean {
    this.deltas.push(deltaMs);
    if (this.deltas.length > WINDOW_FRAMES) this.deltas.shift();
    const p95 = this.p95Ms;
    if (p95 === null) return false;

    if (p95 > P95_BUDGET_MS) {
      this.stableSinceMs = null;
      this.overBudgetSinceMs = this.overBudgetSinceMs ?? nowMs;
      if (nowMs - this.overBudgetSinceMs >= SUSTAIN_BEFORE_DOWNGRADE_MS) {
        this.overBudgetSinceMs = null;
        if (this.level < QUALITY_LADDER.length - 1) {
          this.level += 1;
          this.deltas = []; // measure the NEW level fresh, not the old one's lag
          return true;
        }
      }
      return false;
    }

    this.overBudgetSinceMs = null;
    // Hysteretic recovery: 30s continuously under budget before stepping up.
    this.stableSinceMs = this.stableSinceMs ?? nowMs;
    if (nowMs - this.stableSinceMs >= STABLE_BEFORE_RECOVER_MS && this.level > 0) {
      this.stableSinceMs = null;
      this.level -= 1;
      this.deltas = [];
      return true;
    }
    return false;
  }
}
