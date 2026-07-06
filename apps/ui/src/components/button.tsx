/**
 * The canonical button set from the design system (components doc):
 * primary (ink fill), secondary (canvas + grey-300 border, hover ink border),
 * ghost (transparent, grey-600; dismiss variant grey-400). Small = 13px.
 *
 * Copy contract: button labels say what they do, sentence case, no
 * exclamation marks — enforced by usage, carried by every call site.
 */
import type { ButtonHTMLAttributes } from "react";

export type ButtonVariant = "primary" | "secondary" | "ghost" | "ghost-dismiss";

interface OmniButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  readonly variant: ButtonVariant;
  readonly small?: boolean;
}

const VARIANT_CLASSES: Readonly<Record<ButtonVariant, string>> = {
  primary:
    "bg-[var(--ink)] text-[var(--canvas)] border-none " +
    "disabled:bg-[var(--grey-50)] disabled:text-[var(--grey-300)]",
  secondary:
    "bg-[var(--canvas)] text-[var(--ink)] border border-[var(--grey-300)] " +
    "hover:border-[var(--ink)] disabled:text-[var(--grey-300)] disabled:hover:border-[var(--grey-300)]",
  ghost: "bg-transparent text-[var(--grey-600)] border-none",
  "ghost-dismiss": "bg-transparent text-[var(--grey-400)] border-none",
};

export function OmniButton({ variant, small = false, className, style, ...rest }: OmniButtonProps) {
  const isGhost = variant === "ghost" || variant === "ghost-dismiss";
  // Doc paddings: primary/secondary 10px 18px (small 8px 14px); ghost 10px 8px.
  const padding = isGhost ? "10px 8px" : small ? "8px 14px" : "10px 18px";
  return (
    <button
      type="button"
      {...rest}
      className={`rounded-[var(--radius-control)] font-[family-name:var(--font-body)] font-medium transition-opacity duration-[var(--dur-micro)] disabled:cursor-default ${VARIANT_CLASSES[variant]} ${className ?? ""}`}
      style={{ padding, fontSize: small || isGhost ? 13 : "var(--text-body-size)", ...style }}
    />
  );
}
