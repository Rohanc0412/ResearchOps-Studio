import React from "react";
import { cx } from "../../utils/format";

export function Input({
  className,
  error = false,
  ...props
}: React.InputHTMLAttributes<HTMLInputElement> & {
  error?: boolean;
}) {
  return (
    <input
      className={cx(
        "w-full rounded-lg border bg-obsidian-bg px-3 py-2 text-sm font-sans",
        "text-obsidian-text placeholder:text-obsidian-muted",
        "transition-all duration-150",
        "focus:outline-none focus:ring-2",
        "disabled:cursor-not-allowed disabled:opacity-50",
        error
          ? "border-red-500/50 focus:border-red-500/50 focus:ring-red-500/20"
          : "border-obsidian-border focus:border-obsidian-accent focus:ring-obsidian-accent/20",
        className
      )}
      {...props}
    />
  );
}
