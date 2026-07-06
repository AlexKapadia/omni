/**
 * The Omni logo mark: one ring, six segments — "a camera aperture (it sees),
 * a speaker ring (it hears), an orbit (omni)".
 *
 * Exact construction from the design brief §7: r=38, stroke 11,
 * dasharray 29.8 9.99 (6 segments: (29.8 + 9.99) x 6 = 238.74 = 2*pi*38),
 * rotated -8deg. One colour, ink on canvas, no exceptions.
 */
export function OmniMark({ size }: { readonly size: number }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 100 100"
      aria-hidden
      focusable="false"
    >
      <circle
        cx="50"
        cy="50"
        r="38"
        fill="none"
        stroke="var(--ink)"
        strokeWidth="11"
        strokeDasharray="29.8 9.99"
        transform="rotate(-8 50 50)"
      />
    </svg>
  );
}
