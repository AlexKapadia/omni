/**
 * Naomi affect contract: the typed (valence, arousal, burst) triple every
 * layer of the visual speaks (docs/design/naomi-visual-brief.md §2, after
 * Russell 1980's circumplex model).
 *
 * Sits at the very bottom of the Naomi stack — the tag parser produces it,
 * the parameter mapper consumes it, the store holds it. Pure types + clamps;
 * no DOM, no side effects, fully deterministic.
 */

/** A laugh burst with intensity 0..1; `null` means no burst. */
export interface LaughBurst {
  readonly kind: "laugh";
  /** 0 = barely a chuckle, 1 = full laugh (drives droplet detach + ring pulses). */
  readonly intensity: number;
}

/** The affect triple. valence ∈ [−1,1], arousal ∈ [0,1] (brief §2). */
export interface Affect {
  readonly valence: number;
  readonly arousal: number;
  readonly burst: LaughBurst | null;
}

/** The neutral resting affect — the idle pool (brief table row 1). */
export const IDLE_AFFECT: Affect = { valence: 0, arousal: 0.1, burst: null };

function clamp(value: number, lo: number, hi: number): number {
  // NaN fails every comparison → falls through to `lo` (fail closed to a
  // sane pool rather than propagating NaN into shader uniforms).
  if (Number.isNaN(value)) return lo;
  return Math.min(hi, Math.max(lo, value));
}

/** Clamp an arbitrary triple into the legal affect ranges (deny bad input). */
export function clampAffect(valence: number, arousal: number, burst: LaughBurst | null): Affect {
  return {
    valence: clamp(valence, -1, 1),
    arousal: clamp(arousal, 0, 1),
    burst:
      burst === null
        ? null
        : { kind: "laugh", intensity: clamp(burst.intensity, 0, 1) },
  };
}

/** Burst intensity as a plain number (0 when absent) — mapper convenience. */
export function burstIntensity(affect: Affect): number {
  return affect.burst === null ? 0 : affect.burst.intensity;
}
