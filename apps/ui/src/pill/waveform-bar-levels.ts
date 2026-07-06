/**
 * Waveform math for the dictation pill — the exact numbers from the design
 * brief §8: "2.5px bars · ink on white · driven by real levels · fast attack
 * (0.5), damped decay (0.93) so it feels physical · floor 2px"; pill size
 * 110×18 with 20 bars; idle floor level 0.06 → min bar height 2px.
 *
 * Pure functions only (no canvas, no audio) so every constant and step is
 * exactly testable — the canvas component consumes these verbatim.
 */

export const BAR_WIDTH_PX = 2.5;
export const ATTACK = 0.5;
export const DECAY = 0.93;
export const MIN_BAR_HEIGHT_PX = 2;
export const IDLE_FLOOR_LEVEL = 0.06;

/** Pill waveform geometry pinned by design §07: 110×18, 20 bars. */
export const PILL_WAVEFORM = { width: 110, height: 18, bars: 20 } as const;

/** Even gaps: (w − bars·2.5)/(bars−1), per the reference implementation. */
export function barGapPx(width: number, bars: number): number {
  if (bars <= 1) return 0;
  return (width - bars * BAR_WIDTH_PX) / (bars - 1);
}

/** X of bar i (left edge), from the bar width + even-gap layout. */
export function barXPx(index: number, width: number, bars: number): number {
  return index * (BAR_WIDTH_PX + barGapPx(width, bars));
}

/**
 * One animation step for one bar: fast attack toward a louder target
 * (lv += (target − lv) · 0.5), damped decay otherwise (lv · 0.93) — but
 * never below the target, so a sustained level holds instead of sagging.
 */
export function stepBarLevel(current: number, target: number): number {
  if (target > current) return current + (target - current) * ATTACK;
  return Math.max(target, current * DECAY);
}

/** Bar pixel height for a level: proportional, floored at 2px. */
export function barHeightPx(level: number, canvasHeight: number): number {
  return Math.max(MIN_BAR_HEIGHT_PX, level * canvasHeight);
}

/**
 * Split an analyser time-domain buffer (0..255, 128 = silence) into
 * per-bar targets: mean absolute deviation per bucket, normalised to 0..1.
 * Real levels drive the bars — never synthetic animation.
 */
export function barTargetsFromTimeDomain(samples: Uint8Array, bars: number): number[] {
  const targets = new Array<number>(bars).fill(IDLE_FLOOR_LEVEL);
  if (samples.length === 0) return targets;
  const bucketSize = Math.max(1, Math.floor(samples.length / bars));
  for (let bar = 0; bar < bars; bar += 1) {
    const start = bar * bucketSize;
    const end = Math.min(samples.length, start + bucketSize);
    if (start >= samples.length) break;
    let sum = 0;
    for (let i = start; i < end; i += 1) sum += Math.abs((samples[i] ?? 128) - 128);
    const level = sum / (end - start) / 128; // 0..1
    targets[bar] = Math.max(IDLE_FLOOR_LEVEL, Math.min(1, level * 2.5));
  }
  return targets;
}
