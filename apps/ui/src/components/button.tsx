/**
 * The canonical button set from the design system (components doc):
 * primary (accent fill), secondary (surface + grey-300 border, hover accent border/bg),
 * ghost (transparent, grey-600; dismiss variant ink-secondary). Small = 13px.
 *
 * Copy contract: button labels say what they do, sentence case, no
 * exclamation marks — enforced by usage, carried by every call site.
 */
import type { ButtonHTMLAttributes } from "react";
import type { LucideIcon } from "lucide-react";

export type ButtonVariant = "primary" | "secondary" | "ghost" | "ghost-dismiss";

interface OmniButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  readonly variant: ButtonVariant;
  readonly small?: boolean;
  readonly loading?: boolean;
  readonly icon?: LucideIcon;
}

const VARIANT_CLASSES: Readonly<Record<ButtonVariant, string>> = {
  primary:
    "bg-[var(--accent)] text-[var(--on-accent)] border-none " +
    "hover:bg-[var(--accent-strong)] " +
    "disabled:bg-[var(--grey-50)] disabled:text-[var(--grey-300)] disabled:hover:bg-[var(--grey-50)]",
  secondary:
    // Daylight: secondary buttons are raised paper (--surface), not the
    // tinted canvas beneath them (redesign-brief-v2.md §4.1/§4.3).
    "bg-[var(--surface)] text-[var(--ink)] border border-[var(--grey-300)] " +
    "hover:border-[var(--accent)] hover:bg-[var(--accent-subtle)] " +
    "disabled:text-[var(--grey-300)] disabled:hover:border-[var(--grey-300)] disabled:hover:bg-[var(--surface)]",
  ghost:
    "bg-transparent text-[var(--grey-600)] border-none " +
    "hover:bg-[var(--grey-50)] hover:text-[var(--ink)] " +
    "disabled:text-[var(--grey-300)] disabled:hover:bg-transparent",
  "ghost-dismiss":
    "bg-transparent text-[var(--ink-secondary)] border-none " +
    "hover:bg-[var(--grey-50)] hover:text-[var(--ink)] " +
    "disabled:text-[var(--grey-300)] disabled:hover:bg-transparent",
};

export function OmniButton({
  variant,
  small = false,
  loading = false,
  icon: Icon,
  className,
  children,
  style,
  disabled,
  ...rest
}: OmniButtonProps) {
  const isGhost = variant === "ghost" || variant === "ghost-dismiss";

  // Standard heights and paddings using CSS values:
  // small or ghost gets var(--control-height-sm) (32px), normal gets var(--control-height) (40px)
  const heightClass = small || isGhost ? "h-[var(--control-height-sm)]" : "h-[var(--control-height)]";
  const paddingClass = isGhost ? "px-2" : small ? "px-[var(--space-3)]" : "px-[var(--space-5)]";
  const textClass = small || isGhost ? "text-[13px]" : "text-[var(--text-body-size)]";

  return (
    <button
      type="button"
      disabled={disabled || loading}
      className={`inline-flex items-center justify-center gap-[var(--space-2)] rounded-[var(--radius-control)] font-medium transition-all duration-[var(--dur-micro)] disabled:cursor-default ${heightClass} ${paddingClass} ${textClass} ${VARIANT_CLASSES[variant]} ${className ?? ""}`}
      style={style}
      {...rest}
    >
      {loading && (
        <svg
          className="animate-spin text-current"
          style={{ width: 14, height: 14 }}
          xmlns="http://www.w3.org/2000/svg"
          fill="none"
          viewBox="0 0 24 24"
          aria-hidden="true"
        >
          <circle
            className="opacity-25"
            cx="12"
            cy="12"
            r="10"
            stroke="currentColor"
            strokeWidth="4"
          />
          <path
            className="opacity-75"
            fill="currentColor"
            d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"
          />
        </svg>
      )}
      {!loading && Icon && <Icon className="shrink-0" size={small || isGhost ? 14 : 16} />}
      {children}
    </button>
  );
}

