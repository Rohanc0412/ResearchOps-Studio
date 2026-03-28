import React from "react";
import { cx } from "../../utils/format";

type ButtonVariant = "primary" | "secondary" | "ghost" | "danger";
type ButtonSize = "sm" | "md";

const variantClasses: Record<ButtonVariant, string> = {
  primary:
    "bg-obsidian-accent border-obsidian-accent text-white " +
    "hover:brightness-110 hover:shadow-accent-lg active:brightness-95",
  secondary:
    "bg-transparent border-obsidian-border text-obsidian-muted " +
    "hover:bg-obsidian-surface-elevated hover:text-obsidian-text active:opacity-80",
  ghost:
    "bg-transparent border-transparent text-obsidian-muted " +
    "hover:bg-obsidian-surface-elevated hover:text-obsidian-text active:brightness-90",
  danger:
    "bg-[#2a1515] border-[#5a2020] text-red-400 " +
    "hover:bg-[#331a1a] hover:border-[#6b2525] active:brightness-90",
};

const sizeClasses: Record<ButtonSize, string> = {
  sm: "px-3 py-1.5 text-xs gap-1.5",
  md: "px-4 py-2 text-sm gap-2",
};

export function Button({
  className,
  variant = "primary",
  size = "md",
  loading = false,
  disabled,
  children,
  ...props
}: React.ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: ButtonVariant;
  size?: ButtonSize;
  loading?: boolean;
}) {
  return (
    <button
      disabled={disabled || loading}
      className={cx(
        "inline-flex cursor-pointer items-center justify-center rounded-lg border font-sans font-medium",
        "transition-all duration-150",
        "disabled:cursor-not-allowed disabled:opacity-40",
        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-obsidian-accent focus-visible:ring-offset-1 focus-visible:ring-offset-obsidian-bg",
        variantClasses[variant],
        sizeClasses[size],
        className
      )}
      {...props}
    >
      {loading && (
        <span
          className={cx(
            "inline-block animate-spin rounded-full border-2 border-current border-t-transparent",
            size === "sm" ? "h-3 w-3" : "h-3.5 w-3.5"
          )}
          aria-hidden="true"
        />
      )}
      {children}
    </button>
  );
}
