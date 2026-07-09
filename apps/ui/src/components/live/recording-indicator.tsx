/**
 * Recording indicator for the capture bar — the one place the monochrome
 * system breaks for STATE: a live capture reads as a warm --live dot/ring
 * (state colour only, never decoration). Breathing while live (the product's
 * single permanent animation, frozen under prefers-reduced-motion via the
 * global rule in tokens.css); a quiet grey outline when not recording.
 */
export function RecordingIndicator({ live }: { readonly live: boolean }) {
  return (
    <span
      aria-hidden="true"
      className={live ? "omni-breathe" : undefined}
      style={{
        display: "inline-block",
        width: 12,
        height: 12,
        borderRadius: "50%",
        // --live is the recording state colour (graphic ≥3:1); grey-400 is the
        // decorative idle outline. No raw hex — tokens only.
        border: `3px solid ${live ? "var(--live)" : "var(--grey-400)"}`,
        background: live ? "var(--live)" : "transparent",
        flexShrink: 0,
      }}
    />
  );
}
