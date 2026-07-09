/**
 * The Omni logo mark: one ring, six segments — "a camera aperture (it sees),
 * a speaker ring (it hears), an orbit (omni)".
 *
 * Re-designed to be a premium, beautiful animated fluid wave logo with overlapping
 * glowing gradients and organic bezier waves that rotate and morph dynamically.
 */
export function OmniMark({ size }: { readonly size: number }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 100 100"
      aria-hidden
      focusable="false"
      style={{ overflow: "visible", display: "block" }}
    >
      <defs>
        <linearGradient id="omniGrad1" x1="0%" y1="0%" x2="100%" y2="100%">
          <stop offset="0%" stopColor="var(--accent)" stopOpacity="0.85" />
          <stop offset="100%" stopColor="#4f46e5" stopOpacity="0.25" />
        </linearGradient>
        <linearGradient id="omniGrad2" x1="100%" y1="0%" x2="0%" y2="100%">
          <stop offset="0%" stopColor="#06b6d4" stopOpacity="0.8" />
          <stop offset="100%" stopColor="var(--accent)" stopOpacity="0.15" />
        </linearGradient>
        <linearGradient id="omniGrad3" x1="0%" y1="100%" x2="100%" y2="0%">
          <stop offset="0%" stopColor="#6366f1" stopOpacity="0.75" />
          <stop offset="100%" stopColor="#ec4899" stopOpacity="0.15" />
        </linearGradient>
      </defs>
      <style>
        {`
          @keyframes omniWave1 {
            0% { transform: rotate(0deg) scale(1); }
            50% { transform: rotate(180deg) scale(1.05); }
            100% { transform: rotate(360deg) scale(1); }
          }
          @keyframes omniWave2 {
            0% { transform: rotate(120deg) scale(1.03); }
            50% { transform: rotate(-60deg) scale(0.97); }
            100% { transform: rotate(120deg) scale(1.03); }
          }
          @keyframes omniWave3 {
            0% { transform: rotate(240deg) scale(0.97); }
            50% { transform: rotate(420deg) scale(1.06); }
            100% { transform: rotate(240deg) scale(0.97); }
          }
          @keyframes omniCorePulse {
            0%, 100% { transform: scale(0.92); }
            50% { transform: scale(1.08); }
          }
          .omni-wave-1 {
            transform-origin: 50px 50px;
            animation: omniWave1 7s ease-in-out infinite;
          }
          .omni-wave-2 {
            transform-origin: 50px 50px;
            animation: omniWave2 9s ease-in-out infinite;
          }
          .omni-wave-3 {
            transform-origin: 50px 50px;
            animation: omniWave3 11s ease-in-out infinite;
          }
          .omni-core {
            transform-origin: 50px 50px;
            animation: omniCorePulse 2.5s ease-in-out infinite;
          }
        `}
      </style>
      
      {/* Outer subtle boundary ring */}
      <circle cx="50" cy="50" r="44" fill="none" stroke="var(--grey-200)" strokeWidth="0.75" opacity="0.4" />
      
      {/* Interlocking Fluid Wave Paths (Organic bezier rings that morph/rotate) */}
      <path
        className="omni-wave-1"
        d="M 50 10 C 70 10, 90 30, 90 50 C 90 70, 70 90, 50 90 C 30 90, 10 70, 10 50 C 10 30, 30 10, 50 10 Z"
        fill="url(#omniGrad1)"
        stroke="var(--accent)"
        strokeWidth="1.25"
      />
      <path
        className="omni-wave-2"
        d="M 50 16 C 74 8, 84 38, 84 50 C 84 66, 62 84, 50 84 C 28 92, 16 62, 16 50 C 16 34, 26 24, 50 16 Z"
        fill="url(#omniGrad2)"
        stroke="#06b6d4"
        strokeWidth="1"
      />
      <path
        className="omni-wave-3"
        d="M 50 13 C 62 18, 87 28, 87 50 C 87 72, 72 87, 50 87 C 28 87, 13 72, 13 50 C 13 28, 38 8, 50 13 Z"
        fill="url(#omniGrad3)"
        stroke="#6366f1"
        strokeWidth="1"
      />

      {/* Central active core */}
      <circle
        className="omni-core"
        cx="50"
        cy="50"
        r="8"
        fill="var(--ink)"
      />
    </svg>
  );
}
