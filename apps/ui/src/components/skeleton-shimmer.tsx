/**
 * Skeleton shimmer bars — the loading state on primary surfaces ("never a
 * spinner"). Style comes from the .omni-shimmer utility (app.css), which
 * binds the design keyframes; widths stagger 80%/60% per the components doc.
 */
const STAGGERED_WIDTHS = ["100%", "80%", "60%"] as const;

export function SkeletonShimmer({ lines = 3 }: { readonly lines?: number }) {
  return (
    <div
      role="status"
      aria-label="Loading"
      className="flex w-full flex-col gap-[var(--space-3)]"
    >
      {Array.from({ length: lines }, (_, i) => (
        <div
          key={i}
          aria-hidden="true"
          className="omni-shimmer"
          style={{ width: STAGGERED_WIDTHS[i % STAGGERED_WIDTHS.length] }}
        />
      ))}
    </div>
  );
}
