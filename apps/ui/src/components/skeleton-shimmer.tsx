/**
 * Skeleton shimmer bars — the loading state on primary surfaces ("never a
 * spinner"). Style comes from the .omni-shimmer utility (app.css), which
 * binds the design keyframes; widths stagger 80%/60% per the components doc.
 */
const STAGGERED_WIDTHS = ["80%", "60%"] as const;

export function SkeletonShimmer({ lines = 2 }: { readonly lines?: number }) {
  return (
    <div
      role="status"
      aria-label="Loading"
      className="flex w-full flex-col gap-[var(--space-3)]"
    >
      {Array.from({ length: lines }, (_, i) => (
        <div
          key={i}
          className="omni-shimmer"
          style={{ width: STAGGERED_WIDTHS[i % STAGGERED_WIDTHS.length] }}
        />
      ))}
    </div>
  );
}
