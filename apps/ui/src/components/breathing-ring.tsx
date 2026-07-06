/**
 * The breathing ring — the live-capture heartbeat, the product's ONE
 * permanent animation (opacity 1 -> 0.55, 2.4s sine, from tokens.css).
 *
 * Design brief §7: a small ink circle outline; border weight scales with
 * size (2px at 8px, 2.5px at 10px, 3px at 12px). `breathing` is only true
 * while capture is genuinely live — a static ring otherwise, and always
 * static under prefers-reduced-motion (handled globally in app.css).
 */
export function BreathingRing({
  size,
  breathing,
}: {
  readonly size: 8 | 10 | 12;
  readonly breathing: boolean;
}) {
  const borderPx = size === 8 ? 2 : size === 10 ? 2.5 : 3;
  return (
    <span
      aria-hidden
      className={breathing ? "omni-breathe" : undefined}
      style={{
        display: "inline-block",
        width: size,
        height: size,
        borderRadius: "50%",
        border: `${borderPx}px solid var(--ink)`,
        flexShrink: 0,
      }}
    />
  );
}
